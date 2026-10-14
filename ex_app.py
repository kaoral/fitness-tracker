from flask import Flask, render_template
app = Flask(__name__)

@app.get("/")
def home():
    return render_template("home.html", page_title = "Home")

@app.route("/data_overview")
def data_overview():
    return render_template("data_overview.html", page_title = "Data Overview")

@app.route("/daily")
def daily():
    return render_template("daily.html", page_title = "Daily")