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

<div class="d-flex align-items-center justify-content-between mb-5">
  <img src="{{ url_for('static', filename='precision_logo.png') }}" style="height:100px;">
  <h1 class="text-center flex-grow-1">Boat Data Analyzer</h1>
  <img src="{{ url_for('static', filename='image_copy.png') }}" style="height:100px;">
</div>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-3">
  <div class="col-md-4"><input class="form-control" name="location" placeholder="Emplacement" required></div>
  <div class="col-md-4"><input class="form-control" type="date" name="race_date" required></div>
  <div class="col-md-4"><input class="form-control" type="time" name="race_time" required></div>
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

{% if message %}
<hr class="my-5">
<h3 class="text-center text-danger">{{ message }}</h3>
{% endif %}

{% if table %}
<hr class="my-5">
<h2 class="text-center mb-4">{{ etat }}</h2>

<div class="d-flex justify-content-center mb-4">
  <a class="btn btn-success btn-lg" href="{{ download }}">Télécharger CSV</a>
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
def load_csv_robuste(file):
    raw = pd.read_csv(file, engine="python", sep=",", on_bad_lines="skip")

    header_row = None
    for i in range(min(40, len(raw))):
        row = raw.iloc[i].astype(str).str.lower()
        if "section time" in " ".join(row):
            header_row = i
            break

    if header_row is None:
        raise ValueError("En-tête du fichier non détecté")

    df = raw.iloc[header_row + 1:].copy()
    df.columns = raw.iloc[header_row]
    return df.reset_index(drop=True)

# ================= ANALYSE CALIBRÉE =================
def analyze_dataframe(df, ambient_temp):

    def find_col(keys):
        for c in df.columns:
            for k in keys:
                if k in c.lower():
                    return c
        return None

    cols = {
        "Time": find_col(["section time", "time"]),
        "TPS": find_col(["tps"]),
        "AFR": find_col(["lambda"]),
        "Fuel": find_col(["fuel"]),
        "ECT": find_col(["ect"])
    }

    if None in cols.values():
        raise ValueError("Colonnes essentielles manquantes")

    df["Time"] = pd.to_numeric(df[cols["Time"]], errors="coerce")
    df["TPS"] = pd.to_numeric(df[cols["TPS"]], errors="coerce")
    df["AFR"] = pd.to_numeric(df[cols["AFR"]], errors="coerce")
    df["Fuel"] = pd.to_numeric(df[cols["Fuel"]], errors="coerce")
    df["ECT"] = pd.to_numeric(df[cols["ECT"]], errors="coerce")

    df = df.dropna(subset=["Time", "TPS", "AFR", "Fuel"])
    df = df[df["Time"].diff().fillna(0) >= 0]

    df["Lambda"] = df["AFR"] / 14.7

    tps_bad = ~df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    lambda_bad = ~df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])
    fuel_bad = ~df["Fuel"].between(CFG["fuel_min"], CFG["fuel_max"])
    ect_ok = df["ECT"] <= ambient_temp + CFG["temp_offset"]

    # 🔥 LOGIQUE CHEAT PROPRE
    df["OUT"] = tps_bad & lambda_bad & fuel_bad & ect_ok

    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0.0
    for t, out, dt in zip(df["Time"], df["OUT"], df["dt"]):
        if out:
            cumul += dt
            if cumul >= CFG["cheat_delay"]:
                return df, True, t
        else:
            cumul = 0.0

    return df, False, None

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/upload", methods=["POST"])
def upload():
    try:
        file = request.files["file"]
        ambient_temp = float(request.form["ambient_temp"].replace(",", "."))

        location = request.form["location"]
        race_date = request.form["race_date"]
        race_time = request.form["race_time"]

        df = load_csv_robuste(file)
        df, cheat, cheat_time = analyze_dataframe(df, ambient_temp)

        etat = (
            f"CHEAT – Début à {cheat_time:.2f} s"
            if cheat else
            f"PASS | {location} | {race_date} {race_time}"
        )

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
            etat=etat
        )

    except Exception as e:
        return render_template_string(
            HTML,
            message=f"Erreur d'analyse : {str(e)}"
        )

@app.route("/download")
def download():
    return send_file(os.path.join(UPLOAD_DIR, request.args["fname"]), as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


