from flask import Flask, request, render_template_string, send_file, url_for
import pandas as pd
import os
from datetime import datetime

app = Flask(__name__)

# ================= CONFIG =================
CFG = {
    "tps_min": 90,
    "tps_max": 105,
    "lambda_min": 0.75,
    "lambda_max": 1.05,
    "fuel_min": 40,
    "fuel_max": 60,
    "temp_offset": 20,
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
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<!-- HEADER FIXE -->
<div class="d-flex align-items-center justify-content-between mb-5">
  <img src="{{ url_for('static', filename='precision_logo.png') }}" style="height:100px;">
  <h1 class="text-center flex-grow-1">Boat Data Analyzer</h1>
  <img src="{{ url_for('static', filename='image_copy.png') }}" style="height:100px;">
</div>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">
  <div class="col-md-4">
    <input class="form-control" name="location" placeholder="Emplacement" required>
  </div>
  <div class="col-md-4">
    <input class="form-control" type="date" name="race_date" required>
  </div>
  <div class="col-md-4">
    <input class="form-control" type="time" name="race_time" required>
  </div>
</div>

<div class="row mb-4">
  <div class="col-md-4">
    <input class="form-control" type="number" step="0.1"
           name="ambient_temp"
           placeholder="Température ambiante (°C)" required>
  </div>
</div>

<input class="form-control mb-3" type="file" name="file" required>
<button class="btn btn-primary">Analyser</button>

</form>

{% if table %}
<hr class="my-5">

<!-- RESULTAT EN BAS -->
<h2 class="text-center mb-4 text-success">
  {{ etat_global }}
</h2>

<div class="d-flex justify-content-center mb-4">
  <a class="btn btn-success btn-lg" href="{{ download }}">
    Télécharger CSV
  </a>
</div>

<div class="table-responsive mb-5">
  {{ table|safe }}
</div>
{% endif %}

</div>
</body>
</html>
"""

# ================= CSV ROBUSTE =================
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
    return df.reset_index(drop=True)

# ================= ANALYSE ROBUSTE =================
def analyze_dataframe(df):

    df = df.copy()

    df["Time"] = pd.to_numeric(df["Section Time"], errors="coerce")
    df["TPS"] = pd.to_numeric(df["TPS (Main)"], errors="coerce")
    df["AFR"] = pd.to_numeric(df["Lambda 1"], errors="coerce")
    df["Fuel"] = pd.to_numeric(df["Fuel Pressure"], errors="coerce")
    df["ECT"] = pd.to_numeric(df["ECT"], errors="coerce")

    df = df.dropna(subset=["Time", "TPS", "AFR", "Fuel", "ECT"])
    df = df[df["Time"].diff().fillna(0) >= 0]

    df["Lambda"] = df["AFR"] / 14.7

    df["OUT"] = (
        (~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])) &
        (~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])) &
        (~df["Fuel"].between(CFG["fuel_min"], CFG["fuel_max"]))
    )

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0.0
    cheat_detected = False
    cheat_time = None

    for t, out, dt in zip(df["Time"], df["OUT"], df["dt"]):
        if bool(out):
            cumul += dt
            if cumul >= CFG["cheat_delay"]:
                cheat_detected = True
                cheat_time = t
                break
        else:
            cumul = 0.0

    return df, cheat_detected, cheat_time

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(
        HTML,
        table=None,
        download=None,
        etat_global=""
    )

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]

    location = request.form["location"]
    race_date = request.form["race_date"]
    race_time = request.form["race_time"]

    df = load_link_csv(file)
    df, cheat, cheat_time = analyze_dataframe(df)

    if cheat:
        etat = f"CHEAT – Début à {cheat_time:.2f} s"
    else:
        etat = f"PASS | {location} | {race_date} {race_time}"

    fname = f"result_{datetime.now().timestamp()}.csv"
    path = os.path.join(UPLOAD_DIR, fname)
    df.to_csv(path, index=False)

    table = df.head(100).to_html(
        classes="table table-dark table-striped",
        index=False
    )

    return render_template_string(
        HTML,
        table=table,
        download=url_for("download", fname=fname),
        etat_global=etat
    )

@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )

# ================= RENDER =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

