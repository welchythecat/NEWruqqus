from pathlib import Path

from flask import *
from jinja2.exceptions import TemplateNotFound
from werkzeug.utils import safe_join

from ruqqus.helpers.wrappers import *
from ruqqus.__main__ import app, limiter
from ruqqus.classes import *
from .posts import submit_page

# Assets live in ruqqus/assets/.  Resolved against the package directory
# rather than the process working directory, so the app can be started from
# any cwd (the original used a bare "./assets" path).
ASSETS_DIR = Path(app.root_path) / "assets"

#take care of misc pages that never really change (much)
@app.route('/assets/<path:path>')
@limiter.exempt
def static_service(path):
    return send_from_directory(ASSETS_DIR, path)

@app.route("/robots.txt", methods=["GET"])
def robots_txt():
    return send_file(ASSETS_DIR / "robots.txt")

@app.route("/settings", methods=["GET"])
@auth_required
def settings(v):
    return redirect("/settings/profile")

@app.route("/settings/profile", methods=["GET"])
@auth_required
def settings_profile(v):
    return render_template("settings_profile.html", v=v)

@app.route("/settings/security", methods=["GET"])
@auth_required
def settings_security(v):
    return render_template("settings_security.html", v=v)

@app.route("/help", methods=["GET"])
@auth_desired
def help(v):
    return redirect("/help/terms")

@app.route("/favicon.ico", methods=["GET"])
def favicon():
    return send_file(ASSETS_DIR / "images" / "logo" / "favicon.png")

@app.route("/my_info",methods=["GET"])
@auth_required
def my_info(v):
    return render_template("my_info.html", v=v)

@app.route("/notifications", methods=["GET"])
@auth_required
def notifications(v):
    return v.notifications_page(page=request.args.get("page","1"),
                                   include_read=request.args.get("all",False))

@app.route("/submit", methods=["GET"])
@is_not_banned
def submit_get(v):
    return submit_page(v)

@app.route("/about")
def about_index():
    # Only /about/<path> was routed, so the bare /about used by four nav links
    # 404'd.  Forward it the same way the wildcard route below does.
    return redirect("/help/about")

@app.route("/about/<path:path>")
def about_path(path):
    return redirect(f"/help/{path}")

@app.route("/help/<path:path>")
@auth_desired
def help_path(path, v):
    # safe_join() returns None for anything that escapes "help/".
    template_name = safe_join("help", path + ".html")
    if template_name is None:
        abort(404)
    try:
        return render_template(template_name, v=v)
    except TemplateNotFound:
        abort(404)
