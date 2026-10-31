import time
from flask import *
from sqlalchemy import *

from ruqqus.helpers.wrappers import *

from ruqqus.__main__ import app, db, cache
from ruqqus.classes.submission import Submission
from ruqqus.classes.guild import GuildMember


@cache.memoize(timeout=30)
def frontlist(sort="hot", page=1, user_id=None):
    """
    Ids of the posts on the front page, in order.

    ``user_id`` narrows the listing to the guilds that user has joined.  It is
    a plain parameter rather than something read from the session or the
    request precisely because of the ``@cache.memoize`` above: the memoization
    key is built from this function's arguments, so a per-user filter only
    stays per-user if the user is one of those arguments.  Reading it from
    ``session`` inside the body would cache one user's personal feed and hand
    it to everybody for 30 seconds.  Passing ``None`` is the unfiltered front
    page, which is a separate cache entry again.
    """

    #cutoff=int(time.time())-(60*60*24*30)

    posts = db.query(Submission).filter(#Submission.created_utc>=cutoff,
                                        Submission.is_banned==False,
                                        Submission.is_deleted==False,
                                        Submission.stickied==False)

    if user_id is not None:
        # Only posts filed under a guild this user belongs to.  A subquery on
        # board_members rather than a join, so a post filed under several of
        # the user's guilds is still a single row.
        posts=posts.filter(
            Submission.board_id.in_(
                db.query(GuildMember.board_id).filter_by(user_id=user_id)
            )
        )

    if sort=="hot":
        posts=posts.order_by(text("submissions.rank_hot desc"))
    elif sort=="new":
        posts=posts.order_by(Submission.created_utc.desc())
    elif sort=="disputed":
        posts=posts.order_by(text("submissions.rank_fiery desc"))
    elif sort=="top":
        posts=posts.order_by(text("submissions.score desc"))
    elif sort=="activity":
        posts=posts.order_by(text("submissions.rank_activity desc"))
    else:
        abort(422)

    posts=[x.id for x in posts.offset(25*(page-1)).limit(26).all()]


    return posts



@app.route("/", methods=["GET"])
@auth_desired
def home(v):

    page=int(request.args.get("page",1))

    #prevent invalid paging
    page=max(page, 1)

    sort_method=request.args.get("sort", "hot")

    # "all" is the historical front page -- everything, newest and best alike.
    # "mine" narrows it to the guilds the signed-in user has joined.  Nothing
    # else is a feed we know how to build, so it is a 422 like a bad sort.
    feed=request.args.get("feed", "all")
    if feed not in ("all", "mine"):
        abort(422)

    # A personal feed needs someone to personalise it to.
    if feed=="mine" and not v:
        abort(401)

    user_id=v.id if feed=="mine" else None

    #get list of ids
    ids = frontlist(sort=sort_method, page=page, user_id=user_id)

    #check existence of next page
    next_exists=(len(ids)==26)
    ids=ids[0:25]

    #check if ids exist
    if ids:
        #assemble list of tuples
        i=1
        tups=[]
        for x in ids:
            tups.append((x, i))
            i+=1

        #tuple string
        tups = str(tups).lstrip("[").rstrip("]")
            

        #hit db for entries
        
        posts=db.query(Submission
                       ).from_statement(
                           text(f"""
                            select submissions.*, submissions.ups, submissions.downs
                            from submissions
                            join (values {tups}) as x(id, n) on submissions.id=x.id order by x.n"""
                                )).all()
    else:
        posts=[]

    

    #If page 1, check for sticky
    #
    # Not on the personal feed.  A sticky is a site-wide announcement and is
    # not necessarily filed under a guild the reader has joined, so prepending
    # it would put a post in a feed whose whole contract is "only my guilds".
    # It still heads the global front page exactly as before.
    if page==1 and feed=="all":
        sticky =[]
        sticky=db.query(Submission).filter_by(stickied=True).first()
        if sticky:
            posts=[sticky]+posts

    return render_template("home.html", v=v, listing=posts, next_exists=next_exists, sort_method=sort_method, page=page, feed=feed)
