from flask import Flask
app = Flask(__name__)

@app.get("/")
def home():
    return "<h1> Homepage </h1> <p> This is the Homepage. </p>"

@app.route("/data_overview")
def index():
    return "<h1> Data Overview </h1> <p> This pages provides an overview of all available data. </p>"

@app.route("/daily")
def hello():
    return "<h1> Daily </h1> <p> This page provides an overview of todays data. </p>"