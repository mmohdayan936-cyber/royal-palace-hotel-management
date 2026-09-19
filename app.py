from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from datetime import datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "change-this-secret-key"
DB = "hotel.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rooms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        room_number TEXT UNIQUE NOT NULL,
        room_type TEXT NOT NULL,
        price REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'Available'
    );
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT
    );
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        room_id INTEGER NOT NULL,
        check_in TEXT NOT NULL,
        check_out TEXT NOT NULL,
        nights INTEGER NOT NULL,
        total REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'Booked',
        FOREIGN KEY(customer_id) REFERENCES customers(id),
        FOREIGN KEY(room_id) REFERENCES rooms(id)
    );
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL,
        amount REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'Paid',
        FOREIGN KEY(booking_id) REFERENCES bookings(id)
    );
    """)
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users(username,password) VALUES(?,?)", ("admin","Royal@2026HMS"))
    if conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0] == 0:
        sample = [
            ("101","Single",1200,"Available"),
            ("102","Double",1800,"Available"),
            ("201","Deluxe",2500,"Available"),
            ("202","Suite",3500,"Available")
        ]
        conn.executemany("INSERT INTO rooms(room_number,room_type,price,status) VALUES(?,?,?,?)", sample)
    conn.commit()
    conn.close()

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username,password)).fetchone()
        conn.close()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "rooms": conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0],
        "available": conn.execute("SELECT COUNT(*) FROM rooms WHERE status='Available'").fetchone()[0],
        "booked": conn.execute("SELECT COUNT(*) FROM rooms WHERE status!='Available'").fetchone()[0],
        "customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
    }
    recent = conn.execute("""
        SELECT b.*, c.name customer_name, r.room_number
        FROM bookings b
        JOIN customers c ON c.id=b.customer_id
        JOIN rooms r ON r.id=b.room_id
        ORDER BY b.id DESC LIMIT 5
    """).fetchall()
    conn.close()
    return render_template("dashboard.html", stats=stats, recent=recent)

@app.route("/rooms", methods=["GET","POST"])
@login_required
def rooms():
    conn = get_db()
    if request.method == "POST":
        try:
            conn.execute("INSERT INTO rooms(room_number,room_type,price,status) VALUES(?,?,?,'Available')",
                         (request.form["room_number"], request.form["room_type"], float(request.form["price"])))
            conn.commit()
            flash("Room added successfully.", "success")
        except sqlite3.IntegrityError:
            flash("Room number already exists.", "danger")
        return redirect(url_for("rooms"))
    rows = conn.execute("SELECT * FROM rooms ORDER BY room_number").fetchall()
    conn.close()
    return render_template("rooms.html", rooms=rows)

@app.route("/rooms/delete/<int:room_id>")
@login_required
def delete_room(room_id):
    conn = get_db()
    room = conn.execute("SELECT status FROM rooms WHERE id=?", (room_id,)).fetchone()
    if room and room["status"] == "Available":
        conn.execute("DELETE FROM rooms WHERE id=?", (room_id,))
        conn.commit()
        flash("Room deleted.", "success")
    else:
        flash("Only available rooms can be deleted.", "warning")
    conn.close()
    return redirect(url_for("rooms"))

@app.route("/customers", methods=["GET","POST"])
@login_required
def customers():
    conn = get_db()
    if request.method == "POST":
        conn.execute("INSERT INTO customers(name,phone,email) VALUES(?,?,?)",
                     (request.form["name"], request.form["phone"], request.form["email"]))
        conn.commit()
        flash("Customer added successfully.", "success")
        return redirect(url_for("customers"))
    rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("customers.html", customers=rows)

@app.route("/customers/delete/<int:customer_id>")
@login_required
def delete_customer(customer_id):
    conn = get_db()
    has_booking = conn.execute("SELECT 1 FROM bookings WHERE customer_id=? LIMIT 1", (customer_id,)).fetchone()
    if has_booking:
        flash("Customer with booking history cannot be deleted.", "warning")
    else:
        conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
        conn.commit()
        flash("Customer deleted.", "success")
    conn.close()
    return redirect(url_for("customers"))

@app.route("/bookings", methods=["GET","POST"])
@login_required
def bookings():
    conn = get_db()
    if request.method == "POST":
        customer_id = int(request.form["customer_id"])
        room_id = int(request.form["room_id"])
        check_in = datetime.strptime(request.form["check_in"], "%Y-%m-%d")
        check_out = datetime.strptime(request.form["check_out"], "%Y-%m-%d")
        nights = (check_out - check_in).days
        if nights <= 0:
            flash("Check-out date must be after check-in date.", "danger")
            conn.close()
            return redirect(url_for("bookings"))
        room = conn.execute("SELECT * FROM rooms WHERE id=? AND status='Available'", (room_id,)).fetchone()
        if not room:
            flash("Selected room is not available.", "danger")
            conn.close()
            return redirect(url_for("bookings"))
        total = nights * room["price"]
        cur = conn.execute("""INSERT INTO bookings
            (customer_id,room_id,check_in,check_out,nights,total,status)
            VALUES(?,?,?,?,?,?, 'Booked')""",
            (customer_id, room_id, check_in.strftime("%Y-%m-%d"), check_out.strftime("%Y-%m-%d"), nights, total))
        conn.execute("UPDATE rooms SET status='Booked' WHERE id=?", (room_id,))
        conn.execute("INSERT INTO payments(booking_id,amount,status) VALUES(?,?, 'Unpaid')", (cur.lastrowid,total))
        conn.commit()
        flash("Booking created successfully.", "success")
        conn.close()
        return redirect(url_for("bookings"))
    customers = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    rooms = conn.execute("SELECT * FROM rooms WHERE status='Available' ORDER BY room_number").fetchall()
    rows = conn.execute("""
        SELECT b.*, c.name customer_name, r.room_number, r.room_type
        FROM bookings b
        JOIN customers c ON c.id=b.customer_id
        JOIN rooms r ON r.id=b.room_id
        ORDER BY b.id DESC
    """).fetchall()
    conn.close()
    return render_template("bookings.html", bookings=rows, customers=customers, rooms=rooms)

@app.route("/bookings/checkin/<int:booking_id>")
@login_required
def checkin(booking_id):
    conn = get_db()
    conn.execute("UPDATE bookings SET status='Checked-in' WHERE id=?", (booking_id,))
    conn.execute("""UPDATE rooms SET status='Occupied'
                    WHERE id=(SELECT room_id FROM bookings WHERE id=?)""", (booking_id,))
    conn.commit()
    conn.close()
    flash("Customer checked in.", "success")
    return redirect(url_for("bookings"))

@app.route("/bookings/checkout/<int:booking_id>")
@login_required
def checkout(booking_id):
    conn = get_db()
    conn.execute("UPDATE bookings SET status='Checked-out' WHERE id=?", (booking_id,))
    conn.execute("""UPDATE rooms SET status='Available'
                    WHERE id=(SELECT room_id FROM bookings WHERE id=?)""", (booking_id,))
    conn.execute("UPDATE payments SET status='Paid' WHERE booking_id=?", (booking_id,))
    conn.commit()
    conn.close()
    flash("Customer checked out and payment marked paid.", "success")
    return redirect(url_for("bookings"))

@app.route("/bill/<int:booking_id>")
@login_required
def bill(booking_id):
    conn = get_db()
    booking = conn.execute("""
        SELECT b.*, c.name customer_name, c.phone, c.email,
               r.room_number, r.room_type, r.price,
               p.status payment_status
        FROM bookings b
        JOIN customers c ON c.id=b.customer_id
        JOIN rooms r ON r.id=b.room_id
        LEFT JOIN payments p ON p.booking_id=b.id
        WHERE b.id=?
    """, (booking_id,)).fetchone()
    conn.close()
    if not booking:
        return "Booking not found", 404
    return render_template("bill.html", booking=booking)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
