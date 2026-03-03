from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG HRL =================
CFG = {
    "tps_full_load": 90,
    "rpm_full_load": 6000,
    "fuel_min": 50,
    "cheat_delay": 0.5
}

UPLOAD_DIR = "/tmp"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ================= HTML =================
HTML = """
<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Boat Data Analyzer</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">

<style>
body {
    background-color: #111;
}

.logo-top {
    max-height: 90px;
    width: auto;
}

.logo-hrl {
    max-height: 70px;
    width: auto;
}

.footer-img {
    max-height: 60px;
    width: auto;
}
</style>

</head>

<body class="p-4 text-light">

<div class="container">

<div class="d-flex justify-content-between align-items-center mb-4">
    <img src="{{ url_for('static', filename='logo.png') }}" class="logo-top">
    <img src="{{ url_for('static', filename='hrl.png') }}" class="logo-hrl">
</div>

<h2 class="text-center mb-4">Boat Data Analyzer</h2>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">
  <div class="col-md-4">
    <input class="form-control" name="location" placeholder="Emplacement" required>
  </div>

  <div class="col-md-4">
    <input class="form-control" name="ambient_temp" placeholder="Température ambiante °C" required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}
<hr>

<h3 class="text-center {{ 'text-danger' if cheat else 'text-success' }}">
{{ etat }}
</h3>

<div class="text-center mb-3">
Session : {{ session_info }}
</div>

<div class="table-responsive">
{{ table|safe }}
</div>

<a class="btn btn-success mt-3" href="{{ download }}">Télécharger CSV</a>

{% endif %}

<div class="text-center mt-5">
    <img src="{{ url_for('static', filename='logo.png') }}" class="footer-img">
</div>

</div>
</body>
</html>
"""

# ================= LECTURE CSV =================
def load_link_csv(file):

    raw = pd.read_csv(
        file,
        header=None,
        sep=",",
        engine="python",
        on_bad_lines="skip"
    )

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()

    df.columns = header
    df = df.reset_index(drop=True)

    return df


# ================= ANALYSE HRL =================
def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["RPM"] = pd.to_numeric(df.get("RPM"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")

    df = df.dropna(subset=["Time","TPS","RPM","Fuel"])

    df["dt"] = df["Time"].diff().fillna(0)

    df["FULL_LOAD"] = (
        (df["TPS"] > CFG["tps_full_load"]) &
        (df["RPM"] > CFG["rpm_full_load"])
    )

    df["ILLEGAL"] = (
        df["FULL_LOAD"] &
        (df["Fuel"] < CFG["fuel_min"])
    )

    max_streak = 0
    current_streak = 0

    for illegal, dt in zip(df["ILLEGAL"], df["dt"]):
        if illegal:
            current_streak += dt
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    cheat_detected = max_streak >= CFG["cheat_delay"]

    return df, cheat_detected


# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(
        HTML,
        table=None,
        cheat=False,
        etat="",
        download=None,
        session_info=""
    )


@app.route("/upload", methods=["POST"])
def upload():

    file = request.files["file"]

    location = request.form["location"]
    temp = request.form["ambient_temp"]

    df = load_link_csv(file)
    df, cheat = analyze_dataframe(df)

    if cheat:
        etat = "Datalog NOT compliant with rules"
    else:
        etat = "PASS – Datalog conforme HRL"

    session_info = f"Emplacement: {location} | Température: {temp}°C"

    fname = f"result_{datetime.now().timestamp()}.csv"
    path = os.path.join(UPLOAD_DIR, fname)

    df.to_csv(path, index=False)

    table = df.head(120).to_html(
        classes="table table-dark table-striped",
        index=False
    )

    return render_template_string(
        HTML,
        table=table,
        cheat=cheat,
        etat=etat,
        download=url_for("download", fname=fname),
        session_info=session_info
    )


@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
