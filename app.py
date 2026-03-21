from flask import Flask, render_template, request, jsonify, session, redirect, Response
import datetime, hashlib, sqlite3, os, io, csv

app = Flask(__name__)
app.secret_key = "spendsmart_secret_2024"

DB_FILE = "spendsmart.db"

# ─── Database Setup ──────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row   # lets us access columns by name
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            name     TEXT NOT NULL,
            password TEXT NOT NULL,
            created  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS expenses (
            id          TEXT PRIMARY KEY,
            username    TEXT NOT NULL,
            description TEXT NOT NULL,
            amount      REAL NOT NULL,
            category    TEXT NOT NULL,
            date        TEXT NOT NULL,
            year        INTEGER NOT NULL,
            month       INTEGER NOT NULL,
            FOREIGN KEY(username) REFERENCES users(username)
        );
        CREATE TABLE IF NOT EXISTS budgets (
            username TEXT NOT NULL,
            year     INTEGER NOT NULL,
            month    INTEGER NOT NULL,
            amount   REAL NOT NULL,
            PRIMARY KEY(username, year, month)
        );
        CREATE TABLE IF NOT EXISTS goals (
            id       TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            label    TEXT NOT NULL,
            amount   REAL NOT NULL,
            year     INTEGER NOT NULL,
            month    INTEGER NOT NULL,
            done     INTEGER DEFAULT 0,
            FOREIGN KEY(username) REFERENCES users(username)
        );
    """)
    conn.commit()
    conn.close()

init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ─── Page Routes ─────────────────────────────────────────

@app.route("/")
def index():
    if "username" not in session:
        return redirect("/login")
    return render_template("index.html")

@app.route("/login")
def login_page():
    if "username" in session:
        return redirect("/")
    return render_template("login.html")

# ─── Auth API ────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def register():
    body     = request.get_json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")
    name     = body.get("name", "").strip()

    if not username or not password or not name:
        return jsonify({"error": "All fields are required"}), 400
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    if len(password) < 4:
        return jsonify({"error": "Password must be at least 4 characters"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO users (username, name, password, created) VALUES (?,?,?,?)",
            (username, name, hash_password(password), datetime.date.today().isoformat())
        )
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already taken"}), 409
    finally:
        conn.close()

    session["username"] = username
    session["name"]     = name
    session.permanent   = True
    return jsonify({"success": True, "name": name, "username": username}), 201

@app.route("/api/login", methods=["POST"])
def login():
    body     = request.get_json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    conn.close()

    if not user or user["password"] != hash_password(password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["username"] = username
    session["name"]     = user["name"]
    session.permanent   = True
    return jsonify({"success": True, "name": user["name"], "username": username})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/api/me")
def me():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401
    conn = get_db()
    user = conn.execute("SELECT name FROM users WHERE username=?", (session["username"],)).fetchone()
    conn.close()
    return jsonify({"username": session["username"], "name": user["name"] if user else ""})

# ─── Expense API ─────────────────────────────────────────

@app.route("/api/expenses", methods=["GET", "POST"])
def expenses():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user = session["username"]
    conn = get_db()

    if request.method == "GET":
        year  = request.args.get("year")
        month = request.args.get("month")
        if year and month:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE username=? AND year=? AND month=? ORDER BY date DESC",
                (user, int(year), int(month))
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM expenses WHERE username=? ORDER BY date DESC", (user,)
            ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    body = request.get_json()
    if not body or not body.get("description") or not body.get("amount"):
        return jsonify({"error": "Missing fields"}), 400

    today   = datetime.date.today()
    exp_id  = str(int(datetime.datetime.now().timestamp() * 1000))
    conn.execute(
        "INSERT INTO expenses (id,username,description,amount,category,date,year,month) VALUES (?,?,?,?,?,?,?,?)",
        (exp_id, user, body["description"].strip(), float(body["amount"]),
         body.get("category","Other"), body.get("date", today.isoformat()),
         int(body.get("year", today.year)), int(body.get("month", today.month)))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM expenses WHERE id=?", (exp_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route("/api/expenses/<expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401
    conn = get_db()
    result = conn.execute(
        "DELETE FROM expenses WHERE id=? AND username=?", (expense_id, session["username"])
    )
    conn.commit()
    conn.close()
    if result.rowcount == 0:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"deleted": expense_id})

# ─── Budget API ──────────────────────────────────────────

@app.route("/api/budget", methods=["GET", "POST"])
def budget():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user  = session["username"]
    today = datetime.date.today()
    conn  = get_db()

    if request.method == "GET":
        year  = request.args.get("year",  today.year)
        month = request.args.get("month", today.month)
        row   = conn.execute(
            "SELECT amount FROM budgets WHERE username=? AND year=? AND month=?",
            (user, int(year), int(month))
        ).fetchone()
        conn.close()
        return jsonify({"budget": row["amount"] if row else 0})

    body  = request.get_json()
    year  = int(body.get("year",  today.year))
    month = int(body.get("month", today.month))
    value = float(body.get("budget", 0))
    conn.execute(
        "INSERT INTO budgets (username,year,month,amount) VALUES (?,?,?,?) "
        "ON CONFLICT(username,year,month) DO UPDATE SET amount=excluded.amount",
        (user, year, month, value)
    )
    conn.commit()
    conn.close()
    return jsonify({"budget": value})

# ─── Summary API ─────────────────────────────────────────

@app.route("/api/summary")
def summary():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user  = session["username"]
    today = datetime.date.today()
    year  = int(request.args.get("year",  today.year))
    month = int(request.args.get("month", today.month))

    conn = get_db()
    exps = conn.execute(
        "SELECT * FROM expenses WHERE username=? AND year=? AND month=?",
        (user, year, month)
    ).fetchall()
    brow = conn.execute(
        "SELECT amount FROM budgets WHERE username=? AND year=? AND month=?",
        (user, year, month)
    ).fetchone()
    conn.close()

    total      = sum(e["amount"] for e in exps)
    budget_val = brow["amount"] if brow else 0
    by_cat     = {}
    for e in exps:
        by_cat[e["category"]] = by_cat.get(e["category"], 0) + e["amount"]

    return jsonify({
        "total":       round(total, 2),
        "budget":      budget_val,
        "remaining":   round(budget_val - total, 2),
        "by_category": by_cat,
        "count":       len(exps),
    })

# ─── Export CSV ──────────────────────────────────────────

@app.route("/api/export/csv")
def export_csv():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user  = session["username"]
    year  = request.args.get("year")
    month = request.args.get("month")

    conn = get_db()
    if year and month:
        exps = conn.execute(
            "SELECT * FROM expenses WHERE username=? AND year=? AND month=? ORDER BY date",
            (user, int(year), int(month))
        ).fetchall()
    else:
        exps = conn.execute(
            "SELECT * FROM expenses WHERE username=? ORDER BY date", (user,)
        ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Category", "Amount (INR)"])
    for e in exps:
        writer.writerow([e["date"], e["description"], e["category"], e["amount"]])

    filename = f"spendsmart_{year or 'all'}_{month or 'all'}.csv"
    return Response(
        "\ufeff" + output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ─── Goals API ───────────────────────────────────────────

@app.route("/api/goals", methods=["GET", "POST"])
def goals():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user  = session["username"]
    today = datetime.date.today()
    conn  = get_db()

    if request.method == "GET":
        year  = request.args.get("year")
        month = request.args.get("month")
        if year and month:
            rows = conn.execute(
                "SELECT * FROM goals WHERE username=? AND year=? AND month=?",
                (user, int(year), int(month))
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM goals WHERE username=?", (user,)
            ).fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    body   = request.get_json()
    label  = body.get("label", "").strip()
    amount = float(body.get("amount", 0))
    if not label or amount <= 0:
        return jsonify({"error": "Label and amount required"}), 400

    goal_id = str(int(datetime.datetime.now().timestamp() * 1000))
    conn.execute(
        "INSERT INTO goals (id,username,label,amount,year,month,done) VALUES (?,?,?,?,?,?,0)",
        (goal_id, user, label, amount,
         int(body.get("year", today.year)), int(body.get("month", today.month)))
    )
    conn.commit()
    row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
    conn.close()
    return jsonify(dict(row)), 201

@app.route("/api/goals/<goal_id>", methods=["DELETE", "PATCH"])
def goal_action(goal_id):
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user = session["username"]
    conn = get_db()

    if request.method == "DELETE":
        conn.execute("DELETE FROM goals WHERE id=? AND username=?", (goal_id, user))
        conn.commit()
        conn.close()
        return jsonify({"deleted": goal_id})

    row = conn.execute("SELECT done FROM goals WHERE id=? AND username=?", (goal_id, user)).fetchone()
    if row:
        conn.execute("UPDATE goals SET done=? WHERE id=?", (0 if row["done"] else 1, goal_id))
        conn.commit()
    conn.close()
    return jsonify({"updated": goal_id})

if __name__ == "__main__":
    app.run(debug=True)
