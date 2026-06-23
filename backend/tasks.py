# backend/tasks.py
"""
Funções de email standalone — importadas pelo worker RQ.

Sem Flask, SQLAlchemy ou qualquer objeto de contexto de request.
Todos os argumentos são tipos simples (str) para garantir pickle-safety.
"""
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_reset_email(to_address: str, username: str, reset_url: str) -> None:
    smtp_host = os.getenv("EMAIL_SMTP")
    smtp_user = os.getenv("EMAIL_USER")
    if not smtp_host or not smtp_user:
        logger.warning(
            "EMAIL_SMTP/EMAIL_USER não configurados — email de reset não enviado."
        )
        return

    smtp_port = int(os.getenv("EMAIL_PORTA", "587"))
    smtp_pass = os.getenv("EMAIL_PASS", "")
    from_addr = f"Comemore+ <{smtp_user}>"
    subject = "Redefinição de senha — Comemore+"

    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">
    <tr>
      <td align="center" style="padding:30px 10px;">
        <table width="520" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);max-width:520px;">
          <tr>
            <td style="background:linear-gradient(to right,#fce4ec,#e3f2fd);
                       padding:28px 40px;text-align:center;">
              <span style="font-size:28px;font-weight:700;color:#2c3e50;">
                &#127881; Comemore+
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 40px;">
              <p style="margin:0 0 16px;font-size:16px;color:#333;">
                Olá, <strong>{username}</strong>!
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6;">
                Recebemos uma solicitação para redefinir a senha da sua conta
                no <strong>Comemore+</strong>.
              </p>
              <table cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding:8px 0 28px;">
                    <a href="{reset_url}"
                       style="display:inline-block;background:#1976d2;color:#ffffff;
                              text-decoration:none;font-size:15px;font-weight:600;
                              border-radius:8px;padding:14px 32px;">
                      Redefinir minha senha
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:13px;color:#888;">
                Este link é válido por <strong>1 hora</strong>.
              </p>
              <p style="margin:0 0 24px;font-size:13px;color:#888;">
                Se você não solicitou a redefinição, ignore este email
                — sua senha permanece a mesma.
              </p>
              <hr style="border:none;border-top:1px solid #eee;margin:0 0 20px;">
              <p style="margin:0;font-size:12px;color:#aaa;">
                Caso o botão não funcione, copie e cole o link abaixo no seu navegador:<br>
                <span style="color:#1976d2;word-break:break-all;">{reset_url}</span>
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#f5f5f5;padding:20px 40px;text-align:center;
                       border-top:1px solid #eee;">
              <p style="margin:0;font-size:12px;color:#888;">
                &copy; 2026 Comemore+ &middot; {smtp_user}<br>
                Este é um email automático, não responda.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Olá, {username}!\n\n"
        f"Você solicitou a redefinição de senha da sua conta no Comemore+.\n\n"
        f"Acesse o link abaixo para criar uma nova senha (válido por 1 hora):\n"
        f"{reset_url}\n\n"
        f"Se você não solicitou isso, ignore este email.\n\n"
        f"-- Equipe Comemore+"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_address, msg.as_string())
            logger.info(f"Email de reset enviado para '{to_address}'.")
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Falha ao enviar email de reset para '{to_address}': {e}")


def send_verification_email(to_address: str, verify_url: str) -> bool:
    """Envia email de verificação de conta. Retorna True se enviado, False em falha."""
    smtp_host = os.getenv("EMAIL_SMTP")
    smtp_user = os.getenv("EMAIL_USER")
    if not smtp_host or not smtp_user:
        logger.warning(
            "EMAIL_SMTP/EMAIL_USER não configurados — email de verificação não enviado."
        )
        return False

    smtp_port = int(os.getenv("EMAIL_PORTA", "587"))
    smtp_pass = os.getenv("EMAIL_PASS", "")
    from_addr = f"Comemore+ <{smtp_user}>"
    subject = "Confirme seu email — Comemore+"

    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">
    <tr>
      <td align="center" style="padding:30px 10px;">
        <table width="520" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);max-width:520px;">
          <tr>
            <td style="background:linear-gradient(to right,#fce4ec,#e3f2fd);
                       padding:28px 40px;text-align:center;">
              <span style="font-size:28px;font-weight:700;color:#2c3e50;">
                &#127881; Comemore+
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 40px;">
              <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6;">
                Obrigado por criar sua conta no <strong>Comemore+</strong>!
                Clique no botão abaixo para confirmar seu email e ativar sua conta.
              </p>
              <table cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding:8px 0 28px;">
                    <a href="{verify_url}"
                       style="display:inline-block;background:#2e7d32;color:#ffffff;
                              text-decoration:none;font-size:15px;font-weight:600;
                              border-radius:8px;padding:14px 32px;">
                      Confirmar meu email
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:13px;color:#888;">
                Este link é válido por <strong>24 horas</strong>.
              </p>
              <p style="margin:0 0 24px;font-size:13px;color:#888;">
                Se você não criou uma conta no Comemore+, ignore este email.
              </p>
              <hr style="border:none;border-top:1px solid #eee;margin:0 0 20px;">
              <p style="margin:0;font-size:12px;color:#aaa;">
                Caso o botão não funcione, copie e cole o link abaixo:<br>
                <span style="color:#2e7d32;word-break:break-all;">{verify_url}</span>
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#f5f5f5;padding:20px 40px;text-align:center;
                       border-top:1px solid #eee;">
              <p style="margin:0;font-size:12px;color:#888;">
                &copy; 2026 Comemore+ &middot; {smtp_user}<br>
                Este é um email automático, não responda.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Obrigado por criar sua conta no Comemore+!\n\n"
        f"Confirme seu email acessando o link abaixo (válido por 24 horas):\n"
        f"{verify_url}\n\n"
        f"Se você não criou uma conta, ignore este email.\n\n"
        f"-- Equipe Comemore+"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_address, msg.as_string())
            logger.info(f"Email de verificação enviado para '{to_address}'.")
            return True
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Falha ao enviar email de verificação para '{to_address}': {e}")
        return False


def send_member_invite_email(to_address: str, username: str, reset_url: str) -> bool:
    """Envia email de convite a novo membro com link para definir senha. Retorna True se enviado."""
    smtp_host = os.getenv("EMAIL_SMTP")
    smtp_user = os.getenv("EMAIL_USER")
    if not smtp_host or not smtp_user:
        logger.warning(
            "EMAIL_SMTP/EMAIL_USER não configurados — email de convite não enviado."
        )
        return False

    smtp_port = int(os.getenv("EMAIL_PORTA", "587"))
    smtp_pass = os.getenv("EMAIL_PASS", "")
    from_addr = f"Comemore+ <{smtp_user}>"
    subject = "Você foi convidado para o Comemore+"

    html_body = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;">
    <tr>
      <td align="center" style="padding:30px 10px;">
        <table width="520" cellpadding="0" cellspacing="0"
               style="background:#ffffff;border-radius:12px;overflow:hidden;
                      box-shadow:0 4px 20px rgba(0,0,0,0.08);max-width:520px;">
          <tr>
            <td style="background:linear-gradient(to right,#fce4ec,#e3f2fd);
                       padding:28px 40px;text-align:center;">
              <span style="font-size:28px;font-weight:700;color:#2c3e50;">
                &#127881; Comemore+
              </span>
            </td>
          </tr>
          <tr>
            <td style="padding:36px 40px;">
              <p style="margin:0 0 16px;font-size:16px;color:#333;">
                Olá, <strong>{username}</strong>!
              </p>
              <p style="margin:0 0 24px;font-size:15px;color:#555;line-height:1.6;">
                Você foi adicionado ao <strong>Comemore+</strong>. Clique no botão
                abaixo para definir sua senha e acessar o painel.
              </p>
              <table cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td align="center" style="padding:8px 0 28px;">
                    <a href="{reset_url}"
                       style="display:inline-block;background:#1976d2;color:#ffffff;
                              text-decoration:none;font-size:15px;font-weight:600;
                              border-radius:8px;padding:14px 32px;">
                      Definir minha senha
                    </a>
                  </td>
                </tr>
              </table>
              <p style="margin:0 0 8px;font-size:13px;color:#888;">
                Este link é válido por <strong>1 hora</strong>.
              </p>
              <hr style="border:none;border-top:1px solid #eee;margin:0 0 20px;">
              <p style="margin:0;font-size:12px;color:#aaa;">
                Caso o botão não funcione, copie e cole o link abaixo:<br>
                <span style="color:#1976d2;word-break:break-all;">{reset_url}</span>
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#f5f5f5;padding:20px 40px;text-align:center;
                       border-top:1px solid #eee;">
              <p style="margin:0;font-size:12px;color:#888;">
                &copy; 2026 Comemore+ &middot; {smtp_user}<br>
                Este é um email automático, não responda.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

    text_body = (
        f"Olá, {username}!\n\n"
        f"Você foi adicionado ao Comemore+. Acesse o link abaixo para definir sua senha (válido por 1 hora):\n"
        f"{reset_url}\n\n"
        f"-- Equipe Comemore+"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_address
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port)
        try:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_address, msg.as_string())
            logger.info(f"Email de convite enviado para '{to_address}'.")
            return True
        finally:
            try:
                server.quit()
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Falha ao enviar email de convite para '{to_address}': {e}")
        return False
