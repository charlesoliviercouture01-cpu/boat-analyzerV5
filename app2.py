from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

CFG = {
    "tps_full_load": 90,
    "rpm_full_load": 6000,
    "fuel_min": 50,
    "cheat_delay": 0.5
}

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
.logo { max-height:80px; width:auto; }
</style>
</head>
<body class="bg-dark text-light p-4">

<div class="container">

<div class="d-flex justify-content-between mb-4">
<img src="{{ url_for('static', filename='logo.png') }}" class="logo">
<img src="{{ url_for('static', filename='hrl.png') }}" class="logo">
</div>

<h3 class="text-center mb-4">Boat Data Analyzer</h3>

<form method="post" action="/upload" enctype="multipart/form-data">
<div class="row mb-3">
<div class="col">
<input class="form-control" name="location" placeholder="Emplacement" required>
</div>
<div class="col">
<input class="form-control" name="ambient_temp" placeholder="Température °C" required>
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

<div class="text-center mb-3">
{{ session_info }}
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

# ================= LECTURE RAPIDE =================
def load_link_csv(file):

    raw = pd.read_csv(
        file,
        header=None,
        sep=",",
        engine="c",   # IMPORTANT plus rapide que python
        low_memory=False
    )

    header = raw.iloc[19]
    df = raw.iloc[22:].copy()
    df.columns = header
    df.reset_index(drop=True, inplace=True)

    return df


# ================= ANALYSE ULTRA RAPIDE =================
def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["RPM"] = pd.to_numeric(df.get("RPM"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")

    df.dropna(subset=["Time","TPS","RPM","Fuel"], inplace=True)

    df["dt"] = df["Time"].diff().fillna(0)

    full_load = (
        (df["TPS"] > CFG["tps_full_load"]) &
        (df["RPM"] > CFG["rpm_full_load"])
    )

    illegal = full_load & (df["Fuel"] < CFG["fuel_min"])

    # 🔥 streak vectorisé (pas de boucle lente)
    streak_time = (illegal * df["dt"])

    # regroupe par segments continus
    group = (illegal != illegal.shift()).cumsum()
    streak_sum = streak_time.groupby(group).sum()

    cheat_detected = streak_sum.max() >= CFG["cheat_delay"]

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

    etat = "Datalog NOT compliant with rules" if cheat else "PASS – Datalog conforme HRL"

    session_info = f"Emplacement: {location} | Température: {temp}°C"

    fname = f"result_{datetime.now().timestamp()}.csv"
    path = os.path.join(UPLOAD_DIR, fname)
    df.to_csv(path, index=False)

    # ⚡ IMPORTANT : on limite l'affichage
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
