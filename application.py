import os

from flask import (
    Flask, session, flash, redirect, url_for, render_template, request, jsonify, abort
)
from werkzeug.security import check_password_hash, generate_password_hash
from flask_session import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
import requests

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))


@app.route("/")
def index():
    return render_template('books/index.html')


def get_avg(reviews):
    ratings_sum = 0
    for review in reviews:
        ratings_sum += review[1]

    # perc here is out of 5 * len(reviews)
    perc = ratings_sum / (5 * len(reviews))
    # in order to translate that out of 5 we multiply with 5.
    return perc * 5


@app.route("/<isbn>/details")
def book_details(isbn):
    # info the book
    book = db.execute("SELECT isbn, author, title, year FROM book WHERE isbn = :isbn", {'isbn': isbn}).fetchone()

    # goodreads api response
    res = requests.get("https://www.goodreads.com/book/review_counts.json", 
                                params={"key": "v06woyE0LKD6nNw3OLABwg", "isbns": isbn})
    res = dict(res.json())
    book_dict = res['books'][0]
    avg_ratings_gr = book_dict["average_rating"]
    ratings_count_gr = book_dict["work_ratings_count"]

    # all existing reviews for the book
    reviews = db.execute("""
                        SELECT "user".username, review.rating, (5 - review.rating) AS remRating, review.review
                        FROM review 
                        JOIN "user" 
                        ON review.uid = "user".id
                        WHERE review.isbn = :isbn
                        """,
                        {'isbn': isbn}).fetchall()

    ratings_count_bapp = len(reviews)
    if (ratings_count_bapp != 0):
        avg_ratings_bapp = get_avg(reviews)
    else:
        avg_ratings_bapp = 0

    # Variable to validate if a user has already reviewed or not.
    try:
        review = db.execute("""SELECT id FROM review 
                            WHERE uid = :id AND isbn = :isbn""", 
                            {"id": session['user_id'], "isbn": isbn}).fetchone()
        if review:
            user_reviewed = True
        else:
            user_reviewed = False
    except KeyError:
        user_reviewed = True

    # dynamic bootstrap colors for different users.
    colArr = ["text-primary", "text-success", "text-danger", "text-warning", "text-info"]

    return render_template('books/details.html', book=book, reviews=reviews,
                            user_reviewed=user_reviewed, colArr=colArr,
                            avg_ratings_gr=avg_ratings_gr, ratings_count_gr=ratings_count_gr,
                            avg_ratings_bapp=avg_ratings_bapp, ratings_count_bapp=ratings_count_bapp)


@app.route("/set_ratings", methods=('GET', 'POST'))
def set_ratings():
    if request.method == "POST":
        db.execute(
            'INSERT INTO review (rating, review, uid, isbn) VALUES (:ratings, :review, :id, :isbn)',
            {"ratings": int(request.form["stars"]), "review": request.form["review"],
            "id": session['user_id'], "isbn": request.form["isbn"]}
        )
        db.commit()

        reviews = db.execute("SELECT id, rating FROM review WHERE isbn = :isbn", {"isbn": request.form["isbn"]}).fetchall()
        print(reviews)
        avg_ratings_bapp = get_avg(reviews)

        return jsonify({"avg_rating": avg_ratings_bapp, "count": len(reviews)})


@app.route("/register", methods=('GET', 'POST'))
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        error = None

        if not username:
            error = 'Username is required.'
        elif not password:
            error = 'Password is required.'
        elif db.execute(
            'SELECT id FROM "user" WHERE username = :username', {"username": username}
        ).fetchone() is not None:
            error = 'User {} is already registered.'.format(username)

        if error is None:
            db.execute(
                'INSERT INTO "user" (username, password) VALUES (:username, :password)',
                {"username": username, "password": generate_password_hash(password)}
            )
            db.commit()
            return redirect(url_for('login'))

        flash(error)
        
    return render_template('auth/register.html')


@app.route("/login", methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        error = None
        user = db.execute(
            'SELECT * FROM "user" WHERE username = :username', {"username": username}
        ).fetchone()

        if user is None:
            error = 'Incorrect username.'
        elif not check_password_hash(user['password'], password):
            error = 'Incorrect password.'

        if error is None:
            session.clear()
            session['user_id'] = user['id']
            session['uname'] = user['username']
            return redirect(url_for('index'))

        flash(error)

    return render_template('auth/login.html')


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route("/api/<isbn>")
def api_access(isbn):

    book = db.execute("""SELECT title, author, year, isbn
                      FROM book
                      WHERE book.isbn = :isbn
                      """,
                      {'isbn': isbn}).fetchone()

    if not book:
        abort(404)

    reviews = db.execute("""SELECT COUNT(review.uid), CAST(AVG(rating) AS DECIMAL(10,2))
                        FROM review
                        WHERE review.isbn = :isbn
                        """,
                        {'isbn': isbn}).fetchone()
    
    resp = jsonify({
                    "title": book[0],
                    "author": book[1],
                    "year": book[2],
                    "isbn": isbn,
                    "review_count": reviews[0],
                    "average_score": str(reviews[1])
            })

    return resp