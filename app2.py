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

<div class="d-flex align-items-center justify-content-between mb-4">
  <img src="{{ url_for('static', filename='precision_logo.png') }}" style="height:100px;">
  <h1 class="text-center flex-grow-1">{{ etat_global }}</h1>
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

<div class="row mb-3">
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
<hr>
<a class="btn btn-success" href="{{ download }}">Télécharger CSV</a>
<div class="table-responsive mt-3">{{ table|safe }}</div>
{% endif %}

</div>
</body>
</html>
"""

# ================= CSV LINK (RENDER SAFE) =================
def load_link_csv(file):
    raw = pd.read_csv(
        file,
        sep=None,
        engine="python",
        header=None,
        encoding_errors="ignore"
    )

    header_row = None
    for i in range(len(raw)):
        row = raw.iloc[i].astype(str).str.lower()
        if any("time" in cell for cell in row):
            header_row = i
            break

    if header_row is None:
        raise ValueError("Entête non détectée dans le fichier CSV")

    df = raw.iloc[header_row + 1:].copy()
    df.columns = raw.iloc[header_row]
    return df.reset_index(drop=True)

# ================= ANALYSE =================
def analyze_dataframe(df, ambient_temp):

    df = df.copy()

    df["Time"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["AFR"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")
    df["ECT"] = pd.to_numeric(df.get("ECT"), errors="coerce")

    df = df.dropna(subset=["Time", "TPS", "AFR", "Fuel"])
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
        etat_global="Boat Data Analyzer"
    )

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]

    ambient_temp = float(
        request.form["ambient_temp"]
        .replace(",", ".")
        .strip()
    )

    location = request.form["location"]
    race_date = request.form["race_date"]
    race_time = request.form["race_time"]

    df = load_link_csv(file)
    df, cheat, cheat_time = analyze_dataframe(df, ambient_temp)

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

# ================= ERREUR RENDER =================
@app.errorhandler(Exception)
def handle_error(e):
    return f"<h1>Erreur interne</h1><pre>{str(e)}</pre>", 500

# ================= RENDER ENTRYPOINT =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


