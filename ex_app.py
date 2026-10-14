from flask import Flask
app = Flask(__name__)

@app.get("/")
def home():
    return "<h1> Homepage </h1> <a> This is the Homepage. </a>"

@app.route("/data_overview")
def index():
    return "<h1> Data Overview </h1> <a> This pages provides an overview of all available data. </a>"

@app.route("/daily")
def hello():
    return "<h1> Daily </h1> <a> This page provides an overview of todays data. </a>"