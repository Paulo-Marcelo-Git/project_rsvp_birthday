# backend/app.py
from flask import Flask, render_template, request, redirect, url_for, abort, Response
import pymysql
import os
from functools import wraps

app = Flask(__name__)

def get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST', 'localhost'),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route('/invite/<token>', methods=['GET', 'POST'])
def invite(token):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM invitees WHERE token = %s", (token,))
        invitee = cursor.fetchone()

    if not invitee:
        abort(404)

    if request.method == 'POST':
        response = request.form.get('response')
        if invitee['response'] is None and response in ['yes', 'no']:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE invitees SET response=%s, response_date=NOW() WHERE token=%s",
                    (response, token)
                )
                conn.commit()
        return redirect(url_for('invite', token=token))

    return render_template('invite.html', invitee=invitee)

# -----------------------------
# 🔐 Rotas protegidas de admin
# -----------------------------

def check_auth(username, password):
    return (
        username == os.getenv("ADMIN_USER") and
        password == os.getenv("ADMIN_PASS")
    )

def authenticate():
    return Response(
        "Acesso restrito.\n", 401,
        {"WWW-Authenticate": 'Basic realm="Login Required"'}
    )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/respostas")
@requires_auth
def respostas():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT name, email, phone, response, response_date, token
            FROM invitees
            ORDER BY response_date IS NULL, response_date DESC
        """)
        convidados = cursor.fetchall()
    return render_template('admin_responses.html', convidados=convidados)

if __name__ == "__main__":
    # Para rodar localmente: python app.py
    app.run(host="0.0.0.0", port=8000)
