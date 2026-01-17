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
    "cheat_delay": 0.5,          # secondes
    "min_params_fail": 2         # 🔥 NOUVEAU : minimum de paramètres en faute
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
.logo-box {
  width: 180px;
  display: flex;
  justify-content: center;
}
.logo-box img {
  max-height: 100px;
  max-width: 100%;
  object-fit: contain;
}
</style>
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<!-- HEADER -->
<div class="row align-items-center mb-5">
  <div class="col-3 logo-box">
    <img src="{{ url_for('static', filename='p_logo_zoom.png') }}">
  </div>

  <div class="col-6 text-center">
    <h1 class="m-0">Boat Data Analyzer</h1>
  </div>

  <div class="col-3 logo-box">
    <img src="{{ url_for('static', filename='image_copy.png') }}">
  </div>
</div>

<form method="post" action="/upload" enctype="multipart/form-data">

<div class="row mb-4">
  <div class="col-md-4">
    <input class="form-control" name="location" placeholder="Emplacement" required>
  </div>
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
<hr class="my-4">
<div class="alert alert-danger text-center">{{ message }}</div>
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
    raw = pd.read_csv(
        file,
        engine="python",
        sep=",",
        on_bad_lines="skip"
    )

    header_row = None
    for i in range(min(50, len(raw))):
        row = " ".join(raw.iloc[i].astype(str).str.lower())
        if "time" in row and "section" in row:
            header_row = i
            break

    if header_row is None:
        raise ValueError("Impossible de détecter l’en-tête")

    df = raw.iloc[header_row + 1:].copy()
    df.columns = raw.iloc[header_row]
    df = df.dropna(how="all")

    if df.empty:
        raise ValueError("Aucune donnée valide")

    return df.reset_index(drop=True)

# ================= ANALYSE RECALIBRÉE =================
def analyze_dataframe(df, ambient_temp):

    def find_col(keys):
        for c in df.columns:
            cl = c.lower()
            if any(k in cl for k in keys):
                return c
        return None

    cols = {
        "Time": find_col(["section time", "time"]),
        "TPS": find_col(["tps"]),
        "AFR": find_col(["lambda"]),
        "Fuel": find_col(["fuel"]),
        "ECT": find_col(["ect"])
    }

    if any(v is None for v in cols.values()):
        raise ValueError("Colonnes requises manquantes")

    for k, c in cols.items():
        df[k] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["Time", "TPS", "AFR", "Fuel"])
    df = df[df["Time"].diff().fillna(0) >= 0]

    if df.empty:
        raise ValueError("Aucune donnée exploitable")

    df["Lambda"] = df["AFR"] / 14.7
    df["dt"] = df["Time"].diff().fillna(0)

    cumul = 0.0

    for _, row in df.iterrows():

        fails = []

        if not (CFG["tps_min"] <= row["TPS"] <= CFG["tps_max"]):
            fails.append("TPS")
        if not (CFG["lambda_min"] <= row["Lambda"] <= CFG["lambda_max"]):
            fails.append("Lambda")
        if not (CFG["fuel_min"] <= row["Fuel"] <= CFG["fuel_max"]):
            fails.append("Fuel")
        if row["ECT"] > ambient_temp + CFG["temp_offset"]:
            fails.append("ECT")

        if len(fails) >= CFG["min_params_fail"]:
            cumul += row["dt"]
            if cumul >= CFG["cheat_delay"]:
                return df, True, ", ".join(fails), row["Time"]
        else:
            cumul = 0.0

    return df, False, None, None

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

        df = load_csv_robuste(file)
        df, cheat, params, cheat_time = analyze_dataframe(df, ambient_temp)

        if cheat:
            etat = f"FAIL – {params} à {cheat_time:.2f} s"
        else:
            etat = f"PASS | {location}"

        fname = f"result_{int(datetime.now().timestamp())}.csv"
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
            message=str(e)
        )

@app.route("/download")
def download():
    return send_file(
        os.path.join(UPLOAD_DIR, request.args["fname"]),
        as_attachment=True
    )

# ================= ENTRYPOINT =================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

