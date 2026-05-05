from datetime import datetime
from functools import wraps
import sqlite3

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

app = Flask(__name__)
app.secret_key = "food-donation-secret-key"
DATABASE = "database1.db"


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL,
            phone TEXT,
            address TEXT,
            organization TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donor_id INTEGER NOT NULL,
            ngo_id INTEGER,
            food_type TEXT NOT NULL,
            quantity TEXT NOT NULL,
            pickup_time TEXT NOT NULL,
            location TEXT NOT NULL,
            city TEXT NOT NULL,
            notes TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            accepted_at TEXT,
            FOREIGN KEY (donor_id) REFERENCES users (id),
            FOREIGN KEY (ngo_id) REFERENCES users (id)
        )
        """
    )

    user_columns = {
        column[1] for column in cursor.execute("PRAGMA table_info(users)").fetchall()
    }
    if "phone" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN phone TEXT")
    if "address" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN address TEXT")
    if "organization" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN organization TEXT")
    if "created_at" not in user_columns:
        cursor.execute("ALTER TABLE users ADD COLUMN created_at TEXT")
        cursor.execute(
            "UPDATE users SET created_at = ? WHERE created_at IS NULL",
            (current_timestamp(),),
        )

    donation_columns = {
        column[1] for column in cursor.execute("PRAGMA table_info(donations)").fetchall()
    }
    if "donor_id" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN donor_id INTEGER DEFAULT 1")
    if "ngo_id" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN ngo_id INTEGER")
    if "food_type" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN food_type TEXT")
        if "food" in donation_columns:
            cursor.execute("UPDATE donations SET food_type = food WHERE food_type IS NULL")
    if "pickup_time" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN pickup_time TEXT")
        cursor.execute(
            "UPDATE donations SET pickup_time = 'Coordinate with donor' WHERE pickup_time IS NULL"
        )
    if "city" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN city TEXT")
        cursor.execute("UPDATE donations SET city = 'Not specified' WHERE city IS NULL")
    if "notes" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN notes TEXT")
    if "created_at" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN created_at TEXT")
        cursor.execute(
            "UPDATE donations SET created_at = ? WHERE created_at IS NULL",
            (current_timestamp(),),
        )
    if "accepted_at" not in donation_columns:
        cursor.execute("ALTER TABLE donations ADD COLUMN accepted_at TEXT")

    if "food" in donation_columns:
        cursor.execute(
            "UPDATE donations SET food_type = COALESCE(food_type, food) WHERE food IS NOT NULL"
        )
    if "quantity" in donation_columns:
        cursor.execute(
            "UPDATE donations SET quantity = COALESCE(quantity, 'Not specified') WHERE quantity IS NULL"
        )
    if "location" in donation_columns:
        cursor.execute(
            "UPDATE donations SET location = COALESCE(location, 'Not specified') WHERE location IS NULL"
        )
    if "status" in donation_columns:
        cursor.execute(
            "UPDATE donations SET status = COALESCE(status, 'Available') WHERE status IS NULL"
        )

    admin_exists = cursor.execute(
        "SELECT id FROM users WHERE email = ?", ("admin@foodshare.com",)
    ).fetchone()
    if not admin_exists:
        cursor.execute(
            """
            INSERT INTO users (
                name, email, password, role, phone, address, organization, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Platform Admin",
                "admin@foodshare.com",
                "admin123",
                "admin",
                "+91 90000 00000",
                "Operations Center",
                "FoodShare Admin",
                current_timestamp(),
            ),
        )

    conn.commit()
    conn.close()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            if session.get("role") not in roles:
                flash("You do not have permission to access that page.", "warning")
                return redirect(url_for("home"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def current_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def fetch_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def donation_stats():
    db = get_db()
    return {
        "total_donations": db.execute("SELECT COUNT(*) FROM donations").fetchone()[0],
        "available_donations": db.execute(
            "SELECT COUNT(*) FROM donations WHERE status = 'Available'"
        ).fetchone()[0],
        "accepted_donations": db.execute(
            "SELECT COUNT(*) FROM donations WHERE status = 'Accepted'"
        ).fetchone()[0],
        "total_ngos": db.execute(
            "SELECT COUNT(*) FROM users WHERE role = 'ngo'"
        ).fetchone()[0],
    }


@app.route("/")
def home():
    stats = donation_stats()
    recent_donations = get_db().execute(
        """
        SELECT donations.*, users.name AS donor_name
        FROM donations
        JOIN users ON users.id = donations.donor_id
        ORDER BY donations.id DESC
        LIMIT 3
        """
    ).fetchall()
    return render_template("home.html", stats=stats, recent_donations=recent_donations)


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/register/<role>", methods=["GET", "POST"])
def register(role):
    if role not in {"donor", "ngo"}:
        flash("Invalid registration type.", "danger")
        return redirect(url_for("home"))

    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"].strip()
        phone = request.form["phone"].strip()
        address = request.form["address"].strip()
        organization = request.form["organization"].strip()

        db = get_db()
        existing_user = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing_user:
            flash("An account with this email already exists.", "warning")
            return redirect(url_for("register", role=role))

        db.execute(
            """
            INSERT INTO users (name, email, password, role, phone, address, organization, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, email, password, role, phone, address, organization, current_timestamp()),
        )
        db.commit()
        flash(f"{role.title()} registration completed. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", role=role)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"].strip()

        user = get_db().execute(
            "SELECT * FROM users WHERE email = ? AND password = ?",
            (email, password),
        ).fetchone()

        if not user:
            flash("Invalid email or password.", "danger")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["name"] = user["name"]
        flash(f"Welcome back, {user['name']}!", "success")

        if user["role"] == "donor":
            return redirect(url_for("donor_dashboard"))
        if user["role"] == "ngo":
            return redirect(url_for("ngo_dashboard"))
        return redirect(url_for("admin_dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("home"))


@app.route("/donor", methods=["GET", "POST"])
@login_required
@role_required("donor")
def donor_dashboard():
    db = get_db()
    user_id = session["user_id"]

    if request.method == "POST":
        db.execute(
            """
            INSERT INTO donations (
                donor_id, ngo_id, food_type, quantity, pickup_time, location, city,
                notes, status, created_at, accepted_at
            ) VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 'Available', ?, NULL)
            """,
            (
                user_id,
                request.form["food_type"].strip(),
                request.form["quantity"].strip(),
                request.form["pickup_time"].strip(),
                request.form["location"].strip(),
                request.form["city"].strip(),
                request.form["notes"].strip(),
                current_timestamp(),
            ),
        )
        db.commit()
        flash("Donation listed successfully.", "success")
        return redirect(url_for("donor_dashboard"))

    donor = fetch_user(user_id)
    donations = db.execute(
        """
        SELECT donations.*, ngos.name AS ngo_name, ngos.phone AS ngo_phone
        FROM donations
        LEFT JOIN users AS ngos ON ngos.id = donations.ngo_id
        WHERE donations.donor_id = ?
        ORDER BY donations.id DESC
        """,
        (user_id,),
    ).fetchall()

    ngo_locations = db.execute(
        "SELECT name, organization, address, phone FROM users WHERE role = 'ngo' ORDER BY id DESC"
    ).fetchall()

    return render_template(
        "donor_dashboard.html",
        donor=donor,
        donations=donations,
        ngo_locations=ngo_locations,
    )


@app.route("/ngo")
@login_required
@role_required("ngo")
def ngo_dashboard():
    db = get_db()
    user_id = session["user_id"]
    ngo = fetch_user(user_id)

    available_donations = db.execute(
        """
        SELECT donations.*, donors.name AS donor_name, donors.phone AS donor_phone
        FROM donations
        JOIN users AS donors ON donors.id = donations.donor_id
        WHERE donations.status = 'Available'
        ORDER BY donations.id DESC
        """
    ).fetchall()

    accepted_donations = db.execute(
        """
        SELECT donations.*, donors.name AS donor_name, donors.phone AS donor_phone
        FROM donations
        JOIN users AS donors ON donors.id = donations.donor_id
        WHERE donations.ngo_id = ?
        ORDER BY donations.id DESC
        """,
        (user_id,),
    ).fetchall()

    return render_template(
        "ngo_dashboard.html",
        ngo=ngo,
        available_donations=available_donations,
        accepted_donations=accepted_donations,
    )


@app.route("/accept/<int:donation_id>", methods=["POST"])
@login_required
@role_required("ngo")
def accept_donation(donation_id):
    db = get_db()
    donation = db.execute(
        "SELECT id, status FROM donations WHERE id = ?", (donation_id,)
    ).fetchone()

    if not donation:
        flash("Donation not found.", "danger")
        return redirect(url_for("ngo_dashboard"))

    if donation["status"] != "Available":
        flash("This donation has already been assigned.", "warning")
        return redirect(url_for("ngo_dashboard"))

    db.execute(
        """
        UPDATE donations
        SET status = 'Accepted', ngo_id = ?, accepted_at = ?
        WHERE id = ?
        """,
        (session["user_id"], current_timestamp(), donation_id),
    )
    db.commit()
    flash("Donation accepted successfully.", "success")
    return redirect(url_for("ngo_dashboard"))


@app.route("/admin")
@login_required
@role_required("admin")
def admin_dashboard():
    db = get_db()
    donors = db.execute(
        "SELECT * FROM users WHERE role = 'donor' ORDER BY id DESC"
    ).fetchall()
    ngos = db.execute("SELECT * FROM users WHERE role = 'ngo' ORDER BY id DESC").fetchall()
    donations = db.execute(
        """
        SELECT donations.*, donors.name AS donor_name, ngos.name AS ngo_name
        FROM donations
        JOIN users AS donors ON donors.id = donations.donor_id
        LEFT JOIN users AS ngos ON ngos.id = donations.ngo_id
        ORDER BY donations.id DESC
        """
    ).fetchall()

    return render_template(
        "admin_dashboard.html",
        stats=donation_stats(),
        donors=donors,
        ngos=ngos,
        donations=donations,
    )


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
else:
    init_db()
