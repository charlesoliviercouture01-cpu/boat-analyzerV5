from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

UPLOAD_DIR = "/tmp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Boat Data Analyzer</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">

<style>
.logo {
max-height:80px;
object-fit:contain;
margin:5px;
}
</style>
</head>

<body class="bg-dark text-light p-4">

<div class="container">

<div class="d-flex justify-content-between align-items-center mb-4">

<img src="{{ url_for('static', filename='logo1.png') }}" class="logo">

<h3 class="text-center flex-grow-1">Boat Data Analyzer</h3>

<img src="{{ url_for('static', filename='logo2.png') }}" class="logo">

</div>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">

<div class="col">
<input class="form-control" name="boat" placeholder="Embarcation">
</div>

<div class="col">
<input class="form-control" name="temp" placeholder="Température">
</div>

</div>

<input class="form-control mb-3" type="file" name="file" required>

<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}

<hr>

<h4 class="text-center {{ 'text-danger' if cheat else 'text-success' }}">
{{ etat }}
</h4>

<div class="text-center mb-4">

<b>ECU Serial :</b> {{ ecu }} <br>
<b>Date :</b> {{ date }} <br>
<b>Heure session :</b> {{ heure }}

</div>

<div class="table-responsive">
{{ table|safe }}
</div>

<a class="btn btn-success mt-3" href="{{ download }}">Télécharger CSV</a>

{% endif %}

</div>

</body>
</html>
"""

# ===== LECTURE CSV =====

def load_link_csv(file):

    raw = pd.read_csv(
        file,
        header=None,
        sep=",",
        engine="python",
        on_bad_lines="skip"
    )

    header_text = raw.head(20).astype(str)

    ecu = ""
    date = ""
    heure = ""

    for row in header_text[0]:

        if "ECU" in row or "Serial" in row:
            ecu = row

        if "Date" in row:
            date = row

        if "Time" in row:
            heure = row

    header = raw.iloc[19]

    df = raw.iloc[22:].copy()

    df.columns = header

    df.reset_index(drop=True, inplace=True)

    return df, ecu, date, heure


# ===== ANALYSE CORRIGÉE =====

def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["RPM"] = pd.to_numeric(df.get("RPM"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")

    df.dropna(subset=["Time","TPS","RPM","Fuel"], inplace=True)

    df["dt"] = df["Time"].diff().fillna(0)

    full_load = (
        (df["TPS"] > 90) &
        (df["RPM"] > 6000)
    )

    illegal = full_load & (df["Fuel"] < 50)

    max_duration = 0
    current = 0

    for i in range(len(df)):

        if illegal.iloc[i]:
            current += df["dt"].iloc[i]
            max_duration = max(max_duration, current)
        else:
            current = 0

    cheat = max_duration >= 0.5

    return df, cheat


# ===== PAGE ACCUEIL =====

@app.route("/")
def index():

    return render_template_string(
        HTML,
        table=None,
        cheat=False,
        etat="",
        download=None,
        ecu="",
        date="",
        heure=""
    )


# ===== UPLOAD =====

@app.route("/upload", methods=["POST"])
def upload():

    file = request.files["file"]

    df, ecu, date, heure = load_link_csv(file)

    df, cheat = analyze_dataframe(df)

    if cheat:
        etat = "Datalog NOT compliant with rules"
    else:
        etat = "PASS – Datalog conforme HRL"

    fname = f"result_{datetime.now().timestamp()}.csv"

    path = os.path.join(UPLOAD_DIR, fname)

    df.to_csv(path, index=False)

    table = df.head(80).to_html(
        classes="table table-dark table-striped",
        index=False
    )

    return render_template_string(
        HTML,
        table=table,
        cheat=cheat,
        etat=etat,
        download=url_for("download", fname=fname),
        ecu=ecu,
        date=date,
        heure=heure
    )


# ===== DOWNLOAD =====

@app.route("/download")
def download():

    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )


# ===== RUN =====

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)
