import time
from flask import *
from ruqqus.classes import *
from ruqqus.helpers.wrappers import *
from ruqqus.helpers.base36 import *
from secrets import token_hex
from ruqqus.__main__ import db, app

@app.route("/api/ban_user/<user_id>", methods=["POST"])
@admin_level_required(3)
@validate_formkey
def ban_user(user_id, v):

    # Path parameters arrive as strings but users.id is an integer.  psycopg 3
    # binds a str as a typed VARCHAR parameter, and PostgreSQL then refuses to
    # compare it to an integer column outright.  A non-numeric id is simply not
    # a user, so it is a 400 like any other unknown id.
    try:
        user_id=int(user_id)
    except (TypeError, ValueError):
        abort(400)

    user=db.query(User).filter_by(id=user_id).first()

    if not user:
        abort(400)

    user.is_banned=v.id
    user.ban_reason=request.form.get("reason","")

    db.add(user)
    db.commit()
    
    return (redirect(user.url), user)

@app.route("/api/unban_user/<user_id>", methods=["POST"])
@admin_level_required(3)
@validate_formkey
def unban_user(user_id, v):

    # As in ban_user: the path parameter is a string, users.id is an integer.
    try:
        user_id=int(user_id)
    except (TypeError, ValueError):
        abort(400)

    user=db.query(User).filter_by(id=user_id).first()

    if not user:
        abort(400)

    user.is_banned=0

    db.add(user)
    db.commit()
    
    return (redirect(user.url), user)

@app.route("/api/ban_post/<post_id>", methods=["POST"])
@admin_level_required(3)
@validate_formkey
def ban_post(post_id, v):

    post=db.query(Submission).filter_by(id=base36decode(post_id)).first()

    if not post:
        abort(400)

    post.is_banned=True
    post.is_approved=0
    post.approved_utc=0
    post.stickied=False

    db.add(post)
    db.commit()
    
    return (redirect(post.permalink), post)

@app.route("/api/unban_post/<post_id>", methods=["POST"])
@admin_level_required(3)
@validate_formkey
def unban_post(post_id, v):

    post=db.query(Submission).filter_by(id=base36decode(post_id)).first()

    if not post:
        abort(400)

    post.is_banned=False
    post.is_approved = v.id
    post.approved_utc=int(time.time())

    db.add(post)
    db.commit()
    
    return (redirect(post.permalink), post)


##@app.route("/api/promote/<user_id>/<level>", methods=["POST"])
##@admin_level_required(3)
##@validate_formkey
##def promote(user_id, level, v):
##
##    u = db.query(User).filter_by(id=user_id).first()
##    if not u:
##        abort(404)
##
##    max_level_involved = max(level, u.admin_level)
##
##    try:
##        admin_level_needed={1:3, 2:3, 3:5, 4:5, 5:6}[max_level_involved]
##    except KeyError:
##        abort(400)
##
##    if v.admin_level < admin_level_needed:
##        abort(403)
##
##    u.admin_level=level
##
##    db.add(u)
##    db.commit()
##
##    return redirect(u.url)
    
    
@app.route("/api/distinguish/<post_id>", methods=["POST"])
@admin_level_required(1)
@validate_formkey
def api_distinguish_post(post_id, v):

    post=db.query(Submission).filter_by(id=base36decode(post_id)).first()

    if not post:
        abort(404)

    if not post.author_id == v.id:
        abort(403)

    if post.distinguish_level:
        post.distinguish_level=0
    else:
        post.distinguish_level=v.admin_level

    db.add(post)
    db.commit()

    return (redirect(post.permalink), post)

@app.route("/api/sticky/<post_id>", methods=["POST"])
@admin_level_required(3)
def api_sticky_post(post_id, v):

    
    post=db.query(Submission).filter_by(id=base36decode(post_id)).first()
    if post:
        if post.stickied:
            post.stickied=False
            db.add(post)
            db.commit()
            return redirect(post.permalink)

    already_stickied=db.query(Submission).filter_by(stickied=True).first()

    post.stickied=True
    
    if already_stickied:
        already_stickied.stickied=False
        db.add(already_stickied)
        
    db.add(post)
    db.commit()

    return (redirect(post.permalink), post)

@app.route("/api/ban_comment/<c_id>", methods=["post"])
@admin_level_required(1)
def api_ban_comment(c_id, v):

    comment = db.query(Comment).filter_by(id=base36decode(c_id)).first()
    if not comment:
        abort(404)

    comment.is_banned=True
    comment.is_approved=0
    comment.approved_utc=0

    db.add(comment)
    db.commit()

    return "", 204

@app.route("/api/unban_comment/<c_id>", methods=["post"])
@admin_level_required(1)
def api_unban_comment(c_id, v):

    comment = db.query(Comment).filter_by(id=base36decode(c_id)).first()
    if not comment:
        abort(404)

    comment.is_banned=False
    comment.is_approved=v.id
    comment.approved_utc=int(time.time())

    db.add(comment)
    db.commit()

    return "", 204

@app.route("/api/distinguish_comment/<c_id>", methods=["post"])
@admin_level_required(1)
def api_distinguish_comment(c_id, v):

    comment = db.query(Comment).filter_by(id=base36decode(c_id)).first()
    if not comment:
        abort(404)

    comment.distinguish_level=v.admin_level

    db.add(comment)
    db.commit()

    return "", 204

@app.route("/api/undistinguish_comment/<c_id>", methods=["post"])
@admin_level_required(1)
def api_undistinguish_comment(c_id, v):

    comment = db.query(Comment).filter_by(id=base36decode(c_id)).first()
    if not comment:
        abort(404)

    comment.distinguish_level=0

    db.add(comment)
    db.commit()

    return "", 204
