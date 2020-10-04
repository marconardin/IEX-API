import os

from cs50 import SQL
from flask import Flask, flash, jsonify, redirect, render_template, request, session
from flask_session import Session
from tempfile import mkdtemp
from werkzeug.exceptions import default_exceptions, HTTPException, InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

from datetime import datetime

# Configure application
app = Flask(__name__)

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Ensure responses aren't cached
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_FILE_DIR"] = mkdtemp()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")

# Make sure API key is set
if not os.environ.get("API_KEY"):
    raise RuntimeError("API_KEY not set")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""

    # grab symbols, company names, number of shares purchased
    # for number of shares purchased, will need to aggregate across multiple transactions
    companies = db.execute("""SELECT symbol, company_name, SUM(number_of_shares) AS shares
                              FROM transactions
                              WHERE user_id = :user_id
                              AND bought_or_sold = "bought"
                              GROUP BY symbol
                              ORDER BY transaction_id DESC""",
                              user_id=session["user_id"])

    # for all companies that user has shares in, look up current prices
    for company in companies:
        symbol = company["symbol"]
        curr_stock_price = lookup(symbol)["price"]
        company["price"] = usd(curr_stock_price)
        # subtract number of shares sold for each company in order to have accurate number of current shares
        sold_shares = db.execute("""SELECT SUM(number_of_shares) AS sold_shares
                                    FROM transactions
                                    WHERE user_id = :user_id
                                    AND bought_or_sold = "sold"
                                    AND symbol = :symbol
                                    GROUP BY symbol""",
                                    user_id=session["user_id"],
                                    symbol=symbol)
        if not sold_shares:
            sold_shares = 0
        else:
            sold_shares = sold_shares[0]["sold_shares"]
        # adjust the number of shares currently owned
        company["shares"] = company["shares"] - sold_shares
        # for each company, calculate the total price based on number of shares and the price per share
        company["total"] = curr_stock_price * company["shares"]

    # if company shares total is 0, remove from companies
    companies = [company for company in companies if company["shares"] > 0]

    # look up total cash in users
    total_cash = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id=session["user_id"])[0]["cash"]

    # calculate total cash and assets
    total_assets = sum((company["total"] for company in companies))
    total = total_assets + total_cash

    # convert company value totals to usd
    for company in companies:
        company["total"] = usd(company["total"])

    # render relevant data
    return render_template("/index.html", companies=companies, total_cash=usd(total_cash), total=usd(total))


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # if input is blank
        if not request.form.get("symbol"):
            return apology("Please enter a symbol to purchase stock", 403)

        elif not request.form.get("shares") or int(request.form.get("shares")) <= 0:
            return apology("Please enter the number of shares you'd like to purchase", 403)

        # lookup stock data
        stock_data = lookup(request.form.get("symbol"))

        # record time of purchase
        time_of_purchase = datetime.now()

        # if symbol does not exist
        if stock_data is None:
            return apology("No data for this symbol, please make sure it was entered correctly and try again", 403)

        # select cash from user in users table
        total_cash = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id=session["user_id"])

        # subtract the value of the stocks from the user's money
        updated_cash = total_cash[0]["cash"] - (stock_data["price"] * float(request.form.get("shares")))
        # if the user's money dips below 0, render an apology
        if updated_cash < 0:
            return apology("Sorry, you do not have enough money to complete this purchase.")

        # update the user's cash in the users table with the adjusted value
        db.execute("UPDATE users SET cash = :cash WHERE id = :user_id", cash=updated_cash, user_id=session["user_id"])

        # if table to store information on purchased stocks does not exist, create it
        # table: purchases -- stores the transaction number (PRIMARY KEY), symbol, company name, price per stock, number of stocks, time of purchase, user_id (FOREIGN KEY)
        db.execute("CREATE TABLE IF NOT EXISTS 'transactions' ('transaction_id' INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, 'symbol' TEXT NOT NULL, 'company_name' TEXT NOT NULL, 'price_per_stock' INTEGER NOT NULL, 'number_of_shares' INTEGER NOT NULL, 'time_of_sale' TEXT NOT NULL, 'bought_or_sold' TEXT NOT NULL, 'user_id' INTEGER NOT NULL)")

        # update the purchases table with the new information
        db.execute("INSERT INTO transactions (symbol, company_name, price_per_stock, number_of_shares, time_of_sale, user_id) VALUES (:symbol, :company, :price, :number, :time, 'bought', :user_id)", symbol=stock_data["symbol"], company=stock_data["name"], price=stock_data["price"], number=request.form.get("shares"), time=time_of_purchase, user_id=session["user_id"])

        # return to home
        return redirect("/")

    else:
        return render_template("buy.html")


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""

    # get symbol, bought/sold, price, share_number, and time from transactions
    transactions = db.execute("""SELECT symbol, bought_or_sold, price_per_stock, number_of_shares, time_of_sale
                                 FROM transactions
                                 WHERE user_id = :user_id
                                 ORDER BY time_of_sale DESC""",
                                 user_id=session["user_id"])

    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute("SELECT * FROM users WHERE username = :username",
                          username=request.form.get("username"))

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(rows[0]["hash"], request.form.get("password")):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        # check to make sure stock symbol is entered
        if not request.form.get("symbol"):
            return apology("Please enter a symbol for a quote", 403)

        # look up stock price
        stock_data = lookup(request.form.get("symbol"))

        # handle if no stock data is returned
        if stock_data is None:
            return apology("No data for this symbol, please make sure it was entered correctly and try again", 403)

        # render quoted.html template with stock data
        return render_template("quoted.html", name=stock_data["name"], price=usd(stock_data["price"]), symbol=stock_data["symbol"])

    else:
        return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""

    # Forget any user_id
    session.clear()

    if request.method == "POST":

        # username not entered
        if not request.form.get("username"):
            return apology("Please enter a username", 403)

        # query for username in database
        rows = db.execute("SELECT username FROM users WHERE username = :username", username=request.form.get("username"))

        if len(rows) != 0:
            return apology("This username is already taken, please enter another one", 403)

        # password not entered
        if not request.form.get("password"):
            return apology("Please enter a password", 403)

        # confirmation of password not submitted
        elif not request.form.get("confirmation"):
            return apology("Please confirm your password", 403)

        if request.form.get("password") != request.form.get("confirmation"):
            return apology("Passwords did not match up, please re-enter", 403)

        # update the database
        db.execute("INSERT INTO users (username, hash) VALUES (:username, :hash)",
                    username=request.form.get("username"), hash=generate_password_hash(request.form.get("password")))

        # get user id to update session
        username_id = db.execute("SELECT id FROM users WHERE username = :username", username=request.form.get("username"))
        session["user_id"] = username_id[0]["id"]

        return redirect("/")

    else:
        return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    if request.method == "POST":

        # make sure that user selected a symbol
        form_symbol = request.form.get("symbol")
        if not form_symbol:
            return apology("Please enter the symbol of the stock(s) you want to sell.", 403)

        # make sure user selected a positive integer of shares to sell
        form_shares = int(request.form.get("shares"))
        if not isinstance(form_shares, int) or form_shares < 1:
            return apology("Please enter a positive number of shares to sell.", 403)

        # make sure that user has shares for the symbol
        bought_shares = db.execute("SELECT SUM(number_of_shares) AS bought_shares FROM transactions WHERE symbol = :symbol AND bought_or_sold = 'bought' GROUP BY symbol", symbol=form_symbol)[0]["bought_shares"]
        sold_shares = db.execute("SELECT SUM(number_of_shares) AS sold_shares FROM transactions WHERE symbol = :symbol AND bought_or_sold = 'sold' GROUP BY symbol", symbol=form_symbol)
        if not sold_shares:
            sold_shares = 0
        else:
            sold_shares = sold_shares[0]["sold_shares"]
        if form_shares > (bought_shares - sold_shares):
            return apology("You do not own that many shares to sell.")

        # look up share(s) price
        stock_data = lookup(form_symbol)

        time_of_sale = datetime.now()

        # select cash from user in users table
        total_cash = db.execute("SELECT cash FROM users WHERE id = :user_id", user_id=session["user_id"])[0]["cash"]

        # update user's total cash
        total_cash += float(form_shares) * stock_data["price"]
        db.execute("UPDATE users SET cash = :cash WHERE id = :user_id", cash=total_cash, user_id=session["user_id"])

        # insert sale into the database
        db.execute("INSERT INTO transactions (symbol, company_name, price_per_stock, number_of_shares, time_of_sale, bought_or_sold, user_id) VALUES (:symbol, :company, :price, :number, :time, 'sold', :user_id)", symbol=stock_data["symbol"], company=stock_data["name"], price=stock_data["price"], number=form_shares, time=time_of_sale, user_id=session["user_id"])

        # return to home
        return redirect("/")

    else:
        # get symbols as options for select
        symbols = db.execute("SELECT DISTINCT symbol FROM transactions WHERE user_id = :user_id", user_id=session["user_id"])
        return render_template("sell.html", options=symbols)

    return apology("TODO")


def errorhandler(e):
    """Handle error"""
    if not isinstance(e, HTTPException):
        e = InternalServerError()
    return apology(e.name, e.code)


# Listen for errors
for code in default_exceptions:
    app.errorhandler(code)(errorhandler)
