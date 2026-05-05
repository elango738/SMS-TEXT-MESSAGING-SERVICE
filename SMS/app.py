from flask import Flask, render_template, request, redirect, session
import sqlite3
import os
from twilio.rest import Client

app = Flask(__name__)
app.secret_key = "secret123"

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
else:
    twilio_client = None

def db():
    return sqlite3.connect("database.db")

def init_db():
    con = db()
    cur = con.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, phone_number TEXT UNIQUE)")
    cur.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT, receiver TEXT, message TEXT, status TEXT
    )""")
    cur.execute("CREATE TABLE IF NOT EXISTS groups (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS group_members (group_id INTEGER, username TEXT)")

    # admin
    cur.execute("INSERT OR IGNORE INTO users VALUES ('admin','admin','+1234567890')")

    con.commit()
    con.close()

init_db()

@app.route("/")
def home():
    return redirect("/login")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        con=db();cur=con.cursor()
        username = request.form["username"]
        password = request.form["password"]
        phone = request.form["phone_number"]
        
        if not phone.startswith('+'):
            return "Phone number must include country code (e.g., +91 9876543210)"
        
        try:
            cur.execute("INSERT INTO users VALUES (?,?,?)",
                        (username, password, phone))
            con.commit()
        except:
            return "User or phone number already exists"
        return redirect("/login")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        con=db();cur=con.cursor()
        cur.execute("SELECT * FROM users WHERE username=? AND password=?",
                    (request.form["username"],request.form["password"]))
        if cur.fetchone():
            session["user"]=request.form["username"]
            return redirect("/dashboard")
        return "Invalid login"
    return render_template("login.html")

@app.route("/dashboard")
def dashboard():
    if "user" not in session: return redirect("/login")
    return render_template("dashboard.html",user=session["user"])

def send_sms_via_twilio(to_number, body):
    if not twilio_client or not TWILIO_PHONE_NUMBER:
        return False, "Twilio configuration missing"
    try:
        message = twilio_client.messages.create(
            body=body,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )
        return True, message.sid
    except Exception as e:
        return False, str(e)

@app.route("/send", methods=["GET","POST"])
def send():
    if "user" not in session: return redirect("/login")
    if request.method=="POST":
        msg=request.form["message"]
        if len(msg)>160: return "Message too long"

        receiver_phone = request.form["receiver_phone"]
        con=db();cur=con.cursor()

        # Verify receiver exists
        cur.execute("SELECT username FROM users WHERE phone_number=?", (receiver_phone,))
        receiver = cur.fetchone()
        if not receiver:
            return "Invalid phone number"

        receiver_username = receiver[0]
        success, result = send_sms_via_twilio(receiver_phone, msg)
        if not success:
            return f"SMS send failed: {result}"

        cur.execute("INSERT INTO messages VALUES (NULL,?,?,?,?)",
                    (session["user"], receiver_username, msg, "sent"))
        con.commit()
        return redirect("/dashboard")

    # Get all users' phone numbers for dropdown (except current user)
    con=db();cur=con.cursor()
    cur.execute("SELECT phone_number FROM users WHERE username != ?", (session["user"],))
    contacts = [row[0] for row in cur.fetchall()]
    return render_template("send.html", contacts=contacts)

@app.route("/inbox")
def inbox():
    if "user" not in session: return redirect("/login")
    con=db();cur=con.cursor()
    cur.execute("""SELECT u.phone_number, m.message, m.status FROM messages m
                   JOIN users u ON m.sender = u.username
                   WHERE m.receiver=?""",
                (session["user"],))
    msgs=cur.fetchall()
    cur.execute("UPDATE messages SET status='read' WHERE receiver=?",(session["user"],))
    con.commit()
    return render_template("inbox.html",messages=msgs)

# ---------- GROUP ----------
@app.route("/create_group", methods=["GET","POST"])
def create_group():
    if request.method=="POST":
        con=db();cur=con.cursor()
        cur.execute("INSERT INTO groups VALUES (NULL,?)",(request.form["name"],))
        gid=cur.lastrowid
        cur.execute("INSERT INTO group_members VALUES (?,?)",(gid,session["user"]))
        con.commit()
        return redirect("/dashboard")
    return render_template("create_group.html")

@app.route("/group_message", methods=["GET","POST"])
def group_message():
    con=db();cur=con.cursor()
    if request.method=="POST":
        gid=request.form["group"]
        cur.execute("SELECT username FROM group_members WHERE group_id=?",(gid,))
        for u in cur.fetchall():
            cur.execute("INSERT INTO messages VALUES (NULL,?,?,?,?)",
                        (session["user"],u[0],request.form["message"],"sent"))
        con.commit()
        return redirect("/dashboard")
    cur.execute("SELECT id,name FROM groups")
    groups=cur.fetchall()
    return render_template("group_message.html",groups=groups)

# ---------- ADMIN ----------
@app.route("/admin", methods=["GET","POST"])
def admin():
    if session.get("user")!="admin": return "Access denied"
    if request.method=="POST":
        con=db();cur=con.cursor()
        cur.execute("SELECT username FROM users")
        for u in cur.fetchall():
            cur.execute("INSERT INTO messages VALUES (NULL,?,?,?,?)",
                        ("ADMIN",u[0],request.form["message"],"sent"))
        con.commit()
        return "Campaign sent"
    return render_template("admin.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# DEBUG ENDPOINT - REMOVE IN PRODUCTION
@app.route("/debug")
def debug():
    con=db();cur=con.cursor()
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    cur.execute("SELECT * FROM messages")
    messages = cur.fetchall()
    
    return f"""
    <h2>DEBUG INFO</h2>
    <h3>Users:</h3>{users}
    <h3>Messages:</h3>{messages}
    <a href="/login">Back to Login</a>
    """

app.run(debug=True)
