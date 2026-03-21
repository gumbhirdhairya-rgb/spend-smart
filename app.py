from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json, os, datetime, hashlib

app = Flask(__name__)
app.secret_key = "spendsmart_secret_2024"

USERS_FILE    = "users.json"
EXPENSES_FILE = "expenses.json"

# ─── File Helpers ────────────────────────────────────────

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_expenses():
    if os.path.exists(EXPENSES_FILE):
        with open(EXPENSES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_expenses(data):
    with open(EXPENSES_FILE, "w") as f:
        json.dump(data, f, indent=2)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ─── Page Routes ─────────────────────────────────────────

@app.route("/")
def index():
    print(">>> Checking session:", session)           # debug line
    if "username" not in session:
        print(">>> No user in session, redirecting to login")
        return redirect("/login")
    print(">>> User logged in:", session["username"])
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

    users = load_users()
    if username in users:
        return jsonify({"error": "Username already taken"}), 409

    users[username] = {
        "name":     name,
        "username": username,
        "password": hash_password(password),
        "created":  datetime.date.today().isoformat()
    }
    save_users(users)
    session["username"] = username
    session["name"]     = name
    session.permanent   = True
    return jsonify({"success": True, "name": name, "username": username}), 201

@app.route("/api/login", methods=["POST"])
def login():
    body     = request.get_json()
    username = body.get("username", "").strip().lower()
    password = body.get("password", "")

    users = load_users()
    user  = users.get(username)
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
    users = load_users()
    user  = users.get(session["username"], {})
    return jsonify({"username": session["username"], "name": user.get("name", "")})

# ─── Expense API ─────────────────────────────────────────

@app.route("/api/expenses", methods=["GET", "POST"])
def expenses():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}})

    if request.method == "GET":
        year  = request.args.get("year")
        month = request.args.get("month")
        result = udata["expenses"]
        if year and month:
            result = [e for e in result
                      if e["year"] == int(year) and e["month"] == int(month)]
        return jsonify(result)

    body = request.get_json()
    if not body or not body.get("description") or not body.get("amount"):
        return jsonify({"error": "Missing fields"}), 400

    today   = datetime.date.today()
    expense = {
        "id":          str(int(datetime.datetime.now().timestamp() * 1000)),
        "description": body["description"].strip(),
        "amount":      float(body["amount"]),
        "category":    body.get("category", "Other"),
        "date":        body.get("date", today.isoformat()),
        "year":        int(body.get("year",  today.year)),
        "month":       int(body.get("month", today.month)),
    }
    udata["expenses"].append(expense)
    all_data[user] = udata
    save_expenses(all_data)
    return jsonify(expense), 201

@app.route("/api/expenses/<expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}})

    before = len(udata["expenses"])
    udata["expenses"] = [e for e in udata["expenses"] if e["id"] != expense_id]
    if len(udata["expenses"]) == before:
        return jsonify({"error": "Not found"}), 404

    all_data[user] = udata
    save_expenses(all_data)
    return jsonify({"deleted": expense_id})

@app.route("/api/budget", methods=["GET", "POST"])
def budget():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}})
    today    = datetime.date.today()

    if request.method == "GET":
        year  = request.args.get("year",  today.year)
        month = request.args.get("month", today.month)
        key   = f"{year}_{month}"
        return jsonify({"budget": udata["budgets"].get(key, 0)})

    body  = request.get_json()
    year  = body.get("year",   today.year)
    month = body.get("month",  today.month)
    value = float(body.get("budget", 0))
    key   = f"{year}_{month}"
    udata["budgets"][key] = value
    all_data[user] = udata
    save_expenses(all_data)
    return jsonify({"key": key, "budget": value})

@app.route("/api/summary")
def summary():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}})
    today    = datetime.date.today()

    year  = int(request.args.get("year",  today.year))
    month = int(request.args.get("month", today.month))
    key   = f"{year}_{month}"

    exps        = [e for e in udata["expenses"]
                   if e["year"] == year and e["month"] == month]
    total       = sum(e["amount"] for e in exps)
    budget_val  = udata["budgets"].get(key, 0)
    by_category = {}
    for e in exps:
        cat = e["category"]
        by_category[cat] = by_category.get(cat, 0) + e["amount"]

    return jsonify({
        "total":       round(total, 2),
        "budget":      budget_val,
        "remaining":   round(budget_val - total, 2),
        "by_category": by_category,
        "count":       len(exps),
    })

# ─── Export CSV ──────────────────────────────────────────

@app.route("/api/export/csv")
def export_csv():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    import io, csv
    from flask import Response

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}})

    year  = request.args.get("year")
    month = request.args.get("month")
    exps  = udata["expenses"]
    if year and month:
        exps = [e for e in exps if e["year"]==int(year) and e["month"]==int(month)]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Description", "Category", "Amount (INR)"])
    for e in sorted(exps, key=lambda x: x["date"]):
        writer.writerow([e["date"], e["description"], e["category"], e["amount"]])

    filename = f"spendsmart_{year or 'all'}_{month or 'all'}.csv"
    return Response(
        "\ufeff" + output.getvalue(),   # BOM for Excel UTF-8 support
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# ─── Spending Goals API ──────────────────────────────────

@app.route("/api/goals", methods=["GET", "POST"])
def goals():
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}, "goals": []})
    if "goals" not in udata:
        udata["goals"] = []

    if request.method == "GET":
        year  = request.args.get("year")
        month = request.args.get("month")
        result = udata["goals"]
        if year and month:
            result = [g for g in result
                      if g["year"] == int(year) and g["month"] == int(month)]
        return jsonify(result)

    body  = request.get_json()
    label = body.get("label", "").strip()
    amount = float(body.get("amount", 0))
    today = datetime.date.today()

    if not label or amount <= 0:
        return jsonify({"error": "Label and amount required"}), 400

    goal = {
        "id":     str(int(datetime.datetime.now().timestamp() * 1000)),
        "label":  label,
        "amount": amount,
        "year":   int(body.get("year",  today.year)),
        "month":  int(body.get("month", today.month)),
        "done":   False,
    }
    udata["goals"].append(goal)
    all_data[user] = udata
    save_expenses(all_data)
    return jsonify(goal), 201

@app.route("/api/goals/<goal_id>", methods=["DELETE", "PATCH"])
def goal_action(goal_id):
    if "username" not in session:
        return jsonify({"error": "Not logged in"}), 401

    user     = session["username"]
    all_data = load_expenses()
    udata    = all_data.get(user, {"expenses": [], "budgets": {}, "goals": []})
    if "goals" not in udata:
        udata["goals"] = []

    if request.method == "DELETE":
        udata["goals"] = [g for g in udata["goals"] if g["id"] != goal_id]
        all_data[user] = udata
        save_expenses(all_data)
        return jsonify({"deleted": goal_id})

    if request.method == "PATCH":
        for g in udata["goals"]:
            if g["id"] == goal_id:
                g["done"] = not g["done"]
                break
        all_data[user] = udata
        save_expenses(all_data)
        return jsonify({"updated": goal_id})

if __name__ == "__main__":
    app.run(debug=True)