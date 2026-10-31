from flask import *

from ruqqus.__main__ import Base, db
from ruqqus.classes import *


#Wrappers
def auth_desired(f):
    #decorator for any view that changes if user is logged in (most pages)

    def wrapper(*args, **kwargs):

        if "user_id" in session:
            v=db.query(User).filter_by(id=session["user_id"]).first()
        else:
            v=None
            
        return f(*args, v=v, **kwargs)

    wrapper.__name__=f.__name__
    return wrapper

def auth_required(f):
    #decorator for any view that requires login (ex. settings)

    def wrapper(*args, **kwargs):

        if "user_id" in session:
            v=db.query(User).filter_by(id=session["user_id"]).first()
            
            if not v:
                abort(401)

        else:
            abort(401)

        return f(*args, v=v, **kwargs)

    wrapper.__name__=f.__name__
    return wrapper

def is_not_banned(f):
    #decorator that enforces lack of ban

    def wrapper(*args, **kwargs):

        if "user_id" in session:
            v=db.query(User).filter_by(id=session["user_id"]).first()
            
            if not v:
                abort(401)

            if v.is_banned:
                abort(403)
            
        else:
            abort(401)

        return f(*args, v=v, **kwargs)

    wrapper.__name__=f.__name__
    return wrapper
    

#this wrapper takes args and is a bit more complicated


def admin_level_required(x):

    def wrapper_maker(f):

        def wrapper(*args, **kwargs):


            if "user_id" in session:
                v=db.query(User).filter_by(id=session["user_id"]).first()
                if not v:
                    abort(401)
                
                if v.is_banned:
                    abort(403)

                if v.admin_level < x:
                    abort(403)

            else:
                abort(401)

            response= f(*args, v=v, **kwargs)

            # Views here return either an ordinary Flask value -- including a
            # real response tuple like ("", 204) -- or a (response, model) pair
            # whose second element is an ORM object, which Flask cannot read as
            # a status or as headers.  Only the second kind gets unwrapped.
            # Treating every tuple alike silently turned each 204 into a 200,
            # because ("", 204)[0] is "" and Flask renders that as a 200 body.
            if (isinstance(response, tuple)
                    and len(response) == 2
                    and not isinstance(response[1], (int, str, dict))):
                return response[0]

            return response

        wrapper.__name__=f.__name__
        return wrapper

    return wrapper_maker

def validate_formkey(f):

    """Always use @auth_required or @admin_level_required above @validate_form"""

    def wrapper(*args, v, **kwargs):

        submitted_key = request.values.get("formkey","none")
            
        if not submitted_key:
            print("no submitted key")
            abort(401)

        if not v.validate_formkey(submitted_key):
            abort(401)

        return f(*args, v=v, **kwargs)

    wrapper.__name__=f.__name__
    return wrapper
