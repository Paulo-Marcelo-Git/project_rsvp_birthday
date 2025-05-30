# backend\app.py

from flask import Flask, render_template, request, redirect, url_for, abort, Response, flash
import pymysql
import os
import uuid
from functools import wraps
from datetime import timedelta

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'insira_uma_chave_secreta_aqui')

def get_connection():
    return pymysql.connect(
        host=os.getenv('DB_HOST','localhost'),
        user=os.getenv('DB_USER','root'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME'),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        init_command='SET NAMES utf8mb4'
    )

@app.route('/invite/<token>', methods=['GET','POST'])
def invite(token):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM invitees WHERE token=%s", (token,))
        invitee = cursor.fetchone()

        cursor.execute(
            "SELECT `key`,`value` FROM settings WHERE `key` IN "
            "('question_text','yes_text','no_text','post_yes_text','post_no_text')"
        )
        texts = {r['key']: r['value'] for r in cursor.fetchall()}

    if not invitee:
        abort(404)

    if request.method == 'POST':
        response = request.form.get('response')
        if invitee['response'] is None and response in ['yes','no']:
            with conn.cursor() as cursor2:
                cursor2.execute(
                    "UPDATE invitees SET response=%s, response_date=NOW() WHERE token=%s",
                    (response, token)
                )
            conn.commit()
        return redirect(url_for('invite', token=token))

    return render_template(
        'invite.html',
        invitee=invitee,
        question_text = texts.get('question_text'),
        yes_text      = texts.get('yes_text'),
        no_text       = texts.get('no_text'),
        post_yes_text = texts.get('post_yes_text'),
        post_no_text  = texts.get('post_no_text')
    )

# -----------------------------
# 🔐 Rotas protegidas de admin
# -----------------------------
def check_auth(username,password):
    return username==os.getenv("ADMIN_USER") and password==os.getenv("ADMIN_PASS")

def authenticate():
    return Response("Acesso restrito.\n",401,{"WWW-Authenticate": 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args,**kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username,auth.password):
            return authenticate()
        return f(*args,**kwargs)
    return decorated

@app.route("/admin/respostas")
@requires_auth
def respostas():
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT id,name,email,phone,response,response_date,token
            FROM invitees
            ORDER BY response_date IS NULL, response_date DESC
        """)
        convidados = cursor.fetchall()

        # ajuste de fuso
        for row in convidados:
            if row['response_date']:
                row['response_date'] -= timedelta(hours=3)

        cursor.execute(
            "SELECT `key`,`value` FROM settings WHERE `key` IN "
            "('question_text','yes_text','no_text','post_yes_text','post_no_text')"
        )
        texts = {r['key']: r['value'] for r in cursor.fetchall()}

    return render_template(
        'admin_responses.html',
        convidados=convidados,
        texts=texts
    )

@app.route("/admin/convidados/add", methods=['POST'])
@requires_auth
def add_convidado():
    name  = request.form.get('name')
    email = request.form.get('email') or None
    phone = request.form.get('phone')
    msg   = request.form.get('custom_message') or None

    if not name:
        flash("Nome é obrigatório.", "danger")
        return redirect(url_for('respostas'))

    token = uuid.uuid4().hex
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO invitees (name,email,phone,token,custom_message) "
            "VALUES (%s,%s,%s,%s,%s)",
            (name,email,phone,token,msg)
        )
    conn.commit()
    flash(f"Convidado “{name}” adicionado com sucesso!", "success")
    return redirect(url_for('respostas'))

@app.route("/admin/convidados/<int:id>/delete", methods=['POST'])
@requires_auth
def delete_convidado(id):
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM invitees WHERE id=%s", (id,))
    conn.commit()
    flash("Convidado excluído com sucesso.", "warning")
    return redirect(url_for('respostas'))

@app.route("/admin/textos", methods=['POST'])
@requires_auth
def update_textos():
    q  = request.form.get('question_text') or ""
    y  = request.form.get('yes_text') or ""
    n  = request.form.get('no_text') or ""
    py = request.form.get('post_yes_text') or ""
    pn = request.form.get('post_no_text') or ""
    conn = get_connection()
    with conn.cursor() as cursor:
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('question_text',%s)", (q,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('yes_text',%s)"     , (y,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('no_text',%s)"      , (n,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('post_yes_text',%s)", (py,))
        cursor.execute("REPLACE INTO settings (`key`,`value`) VALUES ('post_no_text',%s)" , (pn,))
    conn.commit()
    flash("Textos atualizados com sucesso!", "success")
    return redirect(url_for('respostas'))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
