
import csv
import hashlib
import json
import re
import secrets
import time
from pathlib import Path


import plotly.graph_objects as go
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException


import datetime
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import uvicorn


USERS_FILE = Path("users.csv")
DATA_FILE = Path("data.csv")
LOG_FILE = Path("logs.txt")
AVATAR_DIR = Path("static/avatars")
SESSION_TIME = 5

# тексты всплывающих сообщений (передаются через ?m=код)
FLASH = {
    "reg_ok": ("ok", "Регистрация прошла успешно! Вы вошли как читатель."),
    "wrong": ("err", "Неверный логин или пароль."),
    "bye": ("ok", "Вы вышли из системы."),
    "session": ("err", "Сессия истекла: прошло больше 5 минут без действий. Войдите снова."),
    "need_login": ("err", "Сначала войдите в систему."),
    "country_saved": ("ok", "Карточка страны обновлена."),
    "country_bad": ("err", "Не удалось сохранить карточку: проверьте числа."),
    "role_ok": ("ok", "Роль пользователя изменена."),
    "role_self": ("err", "Нельзя менять роль самому себе."),
    "del_ok": ("ok", "Пользователь удалён."),
    "del_self": ("err", "Нельзя удалить свой собственный аккаунт."),
    "reg_bad": ("err", "Логин уже занят — придумайте другой."),
}

SESSIONS = {}

def hash_password(password, salt):
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()

def read_users():
    if not USERS_FILE.exists():
        return []
    with open(USERS_FILE, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_users(rows):
    fields = ["login", "password_hash", "salt", "role", "avatar", "created"]
    with open(USERS_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def find_user(login):
    for i in read_users():
        if i["login"] == login:
            return i
    return None


def read_data():
    countries = {}
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) != 3 or row[0] != "country":
                    continue
                try:
                    countries[row[1]] = json.loads(row[2])
                except json.JSONDecodeError:
                    continue
    return countries

def write_data(countries):
    with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["type", "key", "value"])
        for iso in sorted(countries):
            w.writerow(["country", iso,
                        json.dumps(countries[iso], ensure_ascii=False)])


def log(login, action):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{now}] {login}: {action}\n")


def create_session(login, role):
    sid = secrets.token_hex(16)
    SESSIONS[sid] = {"login": login, "role": role, "last": time.time()}
    return sid

def get_user(request):
    sid = request.cookies.get("sid")
    sess = SESSIONS.get(sid)
    if sid is None or sess is None:
        return None
    if time.time() - sess["last"] > SESSION_TIME * 60:
        SESSIONS.pop(sid)
        log(sess["login"], "сессия истекла (5 минут бездействия)")
        request.state.session_expired = True
        return None
    user = find_user(sess["login"])
    if user is None:
        SESSIONS.pop(sid)
        return None
    sess["last"] = time.time()
    return user

def flash_from_request(request):
    code = request.query_params.get("m")
    if code in FLASH:
        kind, text = FLASH[code]
        return {"kind": kind, "text": text}
    return None


def need_login_response(request):
    code = "session" if getattr(request.state, "session_expired", False) else "need_login"
    return RedirectResponse(f"/login?m={code}", 303)


def render(request, template, context, status=200):
    context.setdefault("user", get_user(request))
    context.setdefault("flash", flash_from_request(request))
    return templates.TemplateResponse(request, template, context, status_code=status)


def page_forbidden(request):
    return render(request, "403.html", {}, status=403)

#отрисовка карты
def build_map(countries):
    """Собирает HTML-код choropleth-карты мира из справочника стран."""
    iso_codes = sorted(countries.keys())
    names = [countries[i]["name"] for i in iso_codes]
    fig = go.Figure(go.Choropleth(
        locations=iso_codes,
        z=list(range(1, len(iso_codes) + 1)),
        text=names,
        hovertemplate="<b>%{text}</b><br><i>нажмите, чтобы открыть карточку</i><extra></extra>",
        colorscale=[[0.0, "#8ed4f5"], [0.55, "#4da8e0"], [1.0, "#5fbf74"]],
        showscale=False,
        marker_line_color="#ffffff",
        marker_line_width=0.6,
    ))
    fig.update_geos(
        resolution=50,
        projection_type="natural earth",
        showcoastlines=True, coastlinecolor="#a8c4d8",
        showland=True, landcolor="#eef7ee",
        showocean=True, oceancolor="#dcf0fb",
        showframe=False,
    )
    fig.update_layout(margin={"r": 0, "t": 0, "l": 0, "b": 0},
                      paper_bgcolor="rgba(0,0,0,0)")
    return fig.to_html(full_html=False, include_plotlyjs=False, div_id="world-map",
                       config={"topojsonURL": "/static/maps/"})


app = FastAPI(title="Мировой Атлас")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

def create_default_files():
    if not USERS_FILE.exists():
        admin_salt = secrets.token_hex(8)
        reader_salt = secrets.token_hex(8)
        write_users([
            {"login": "adm", "password_hash": hash_password("123", admin_salt),
             "salt": admin_salt, "role": "admin", "avatar": "/static/avatars/admin.svg",
             "created": datetime.datetime.now().strftime("%Y-%m-%d")},
            {"login": "reader", "password_hash": hash_password("reader123", reader_salt),
             "salt": reader_salt, "role": "reader", "avatar": "/static/avatars/reader.svg",
             "created": datetime.datetime.now().strftime("%Y-%m-%d")},
        ])
        log("admin", "создан файл users.csv с тестовыми аккаунтами admin и reader")
create_default_files()
MAP_HTML = build_map(read_data())

#логи
@app.middleware("http")
async def log_visits(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static"):
        return response
    response.headers["Cache-Control"] = "no-store"
    response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.method == "GET":
        sid = request.cookies.get("sid")
        login = SESSIONS[sid]["login"] if sid in SESSIONS else "гость"
        log(login, f"переход на страницу {request.url.path}")
    return response

@app.get("/", response_class=HTMLResponse)
async def main_page(request: Request):
    user = get_user(request)
    if user is None:
        if getattr(request.state, "session_expired", False):
            return RedirectResponse("/?m=session", 303)
        return render(request, "choice.html", {})
    countries = read_data()
    #рендер карты
    countries_json = json.dumps(countries, ensure_ascii=False).replace("<", "\\u003c")
    return render(request, "index.html", {
        "map_html": MAP_HTML, "countries_json": countries_json,
        "country_count": len(countries),
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if get_user(request) is not None:
        return RedirectResponse("/", 303)
    return render(request, "login.html", {})

@app.post("/login")
async def login_post(request: Request, login: str = Form(...),
                     password: str = Form(...)):
    user = find_user(login.strip())
    if user is None or hash_password(password, user["salt"]) != user["password_hash"]:
        log(login.strip() or "гость", "неудачная попытка входа")
        return RedirectResponse("/login?m=wrong", 303)
    sid = create_session(user["login"], user["role"])
    log(user["login"], f"вход в систему (роль: {user['role']})")
    response = RedirectResponse("/", 303)
    response.set_cookie("sid", sid, 
                        max_age=SESSION_TIME * 60,
                        secure=True)
    return response

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    if get_user(request) is not None:
        return RedirectResponse("/", 303)
    return render(request, "register.html", {})


@app.post("/register")
async def register_post(request: Request, login: str = Form(...),
                        password: str = Form(...),
                        photo: UploadFile = File(None)):
    login = re.sub(r"[^a-zA-Z0-9_-]", "", login.strip())
    if not login or find_user(login) is not None:
        return RedirectResponse("/register?m=reg_bad", 303)
    if photo and photo.filename:
        ext = Path(photo.filename).suffix.lower() or ".png"
        AVATAR_DIR.mkdir(parents=True, exist_ok=True)
        (AVATAR_DIR / f"{login}{ext}").write_bytes(await photo.read())
        avatar = f"/static/avatars/{login}{ext}"
    else:
        avatar = "/static/avatars/reader.svg"
    salt = secrets.token_hex(8)
    rows = read_users()
    rows.append({"login": login, "password_hash": hash_password(password, salt),
                 "salt": salt, "role": "reader",
                 "avatar": avatar,
                 "created": datetime.datetime.now().strftime("%Y-%m-%d")})
    write_users(rows)
    log(login, "регистрация нового пользователя (роль: читатель)")
    sid = create_session(login, "reader")
    log(login, "вход в систему (роль: reader)")
    response = RedirectResponse("/?m=reg_ok", 303)
    response.set_cookie("sid", sid, 
                        max_age=SESSION_TIME * 60,
                        secure=True)
    return response

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    return render(request, "profile.html", {})


@app.get("/logout")
async def logout(request: Request):
    user = get_user(request)
    sid = request.cookies.get("sid")
    if sid in SESSIONS:
        SESSIONS.pop(sid)
    if user:
        log(user["login"], "выход из системы")
    response = RedirectResponse("/?m=bye", 303)
    response.delete_cookie("sid")
    return response

@app.get("/users", response_class=HTMLResponse)
async def users_page(request: Request):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка открыть страницу пользователей (нет прав)")
        return page_forbidden(request)
    return render(request, "users.html", {"users": read_users()})


@app.post("/users/role")
async def role_post(request: Request, login: str = Form(...), role: str = Form(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], "попытка изменить роль пользователя (нет прав)")
        return page_forbidden(request)
    if login == user["login"] or role not in ("admin", "reader"):
        return RedirectResponse("/users?m=role_self", 303)
    rows = read_users()
    for r in rows:
        if r["login"] == login:
            r["role"] = role
    write_users(rows)
    for sess in SESSIONS.values():
        if sess["login"] == login:
            sess["role"] = role
    log(user["login"], f"изменил роль пользователя {login} на {role}")
    return RedirectResponse("/users?m=role_ok", 303)

def remove_user_by_login(login: str) -> None:
    users = read_users()
    updated_users = []
    for user in users:
        if user["login"] != login:
            updated_users.append(user)
    write_users(updated_users)
def clear_user_sessions(login: str) -> None:
    sids_to_delete = []
    for sid, session_data in SESSIONS.items():
        if session_data["login"] == login:
            sids_to_delete.append(sid)
    for sid in sids_to_delete:
        SESSIONS.pop(sid, None)

@app.post("/users/delete")
async def delete_post(request: Request, login: str = Form(...)):
    current_user = get_user(request)
    if current_user is None:
        return need_login_response(request)

    if current_user["role"] != "admin":
        log(current_user["login"], "попытка удалить пользователя (нет прав)")
        return page_forbidden(request)

    if login == current_user["login"]:
        return RedirectResponse("/users?m=del_self", 303)
    remove_user_by_login(login)
    clear_user_sessions(login)
    log(current_user["login"], f"удалил пользователя {login}")
    return RedirectResponse("/users?m=del_ok", 303)

@app.post("/country")
async def country_post(request: Request, iso: str = Form(...),
                       name: str = Form(""), info: str = Form(...),
                       population: str = Form(...), area: str = Form(...)):
    user = get_user(request)
    if user is None:
        return need_login_response(request)
    if user["role"] != "admin":
        log(user["login"], f"попытка изменить карточку страны {iso} (нет прав)")
        return page_forbidden(request)
    countries = read_data()
    country = countries.get(iso.upper())
    if country is None:
        return RedirectResponse("/", 303)
    try:
        country["population"] = int(float(population.replace(" ", "").replace(",", ".")))
        country["area"] = round(float(area.replace(" ", "").replace(",", ".")), 2)
    except ValueError:
        return RedirectResponse("/?m=country_bad", 303)
    if name.strip():
        country["name"] = name.strip()
    country["info"] = info.strip()
    #обновление карты сразу после кнопки
    write_data(countries)
    global MAP_HTML
    MAP_HTML = build_map(countries)
    log(user["login"], f"обновил карточку страны {country['name']} ({iso.upper()})")
    return RedirectResponse("/?m=country_saved#map", 303)

@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        log("гость", f"переход на несуществующую страницу {request.url.path}")
        return render(request, "404.html", {"path": request.url.path}, status=404)
    if exc.status_code == 405:
        return render(request, "404.html", {"path": request.url.path}, status=405)
    return render(request, "403.html", {}, status=exc.status_code)

def ensure_cert():
    key_file = Path("key.pem")
    cert_file = Path("cert.pem")
    if not (key_file.exists() and cert_file.exists()):
        key = rsa.generate_private_key(65537, 2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder()
                .subject_name(name).issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now)
                .not_valid_after(now + datetime.timedelta(days=365))
                .sign(key, hashes.SHA256()))
        key_file.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption()))
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return str(key_file), str(cert_file)

if __name__ == "__main__":
    key_pem, cert_pem = ensure_cert()
    uvicorn.run(app, host="127.0.0.1", 
                port=8000,
                ssl_keyfile=key_pem, 
                ssl_certfile=cert_pem)
