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
    "ect_offset": 20,
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
.header-row { height: 130px; }
.logo-box { height: 130px; display:flex; align-items:center; justify-content:center; }
.logo-box img { max-height:115px; object-fit:contain; }
.title-box { height:130px; display:flex; align-items:center; justify-content:center; }

table { text-align:center; }
th { background-color:#222 !important; }
</style>
</head>

<body class="p-4 bg-dark text-light">
<div class="container">

<div class="row header-row mb-5">
  <div class="col-3 logo-box">
    <img src="{{ url_for('static', filename='p_logo_zoom.png') }}">
  </div>
  <div class="col-6 title-box">
    <h1 class="m-0 text-center">Boat Data Analyzer</h1>
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

{% if table %}
<hr class="my-5">
<h2 class="text-center mb-4 {{ status_color }}">
  {{ etat_global }}
</h2>

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

# ================= CSV =================
def load_link_csv(file):
    raw = pd.read_csv(file, header=None, sep=",", engine="python", on_bad_lines="skip")
    header = raw.iloc[19]
    df = raw.iloc[22:].copy()
    df.columns = header
    return df.reset_index(drop=True)

# ================= ANALYSE =================
def analyze_dataframe(df, ambient_temp):

    df = df.copy()

    df["Time (s)"] = pd.to_numeric(df.get("Section Time"), errors="coerce")
    df["TPS"] = pd.to_numeric(df.get("TPS (Main)"), errors="coerce")
    df["AFR"] = pd.to_numeric(df.get("Lambda 1"), errors="coerce")
    df["Fuel Pressure"] = pd.to_numeric(df.get("Fuel Pressure"), errors="coerce")
    df["ECT"] = pd.to_numeric(df.get("ECT"), errors="coerce")

    df = df.dropna(subset=["Time (s)", "TPS", "AFR", "Fuel Pressure", "ECT"])
    df = df[(df["TPS"]>0)&(df["AFR"]>0)&(df["Fuel Pressure"]>0)&(df["ECT"]>0)]
    df = df[df["Time (s)"].diff().fillna(0) >= 0]

    df["Lambda"] = (df["AFR"] / 14.7).round(3)

    df["TPS OK"] = df["TPS"].between(CFG["tps_min"], CFG["tps_max"])
    df["Lambda OK"] = df["Lambda"].between(CFG["lambda_min"], CFG["lambda_max"])
    df["Fuel OK"] = df["Fuel Pressure"].between(CFG["fuel_min"], CFG["fuel_max"])
    df["ECT OK"] = df["ECT"] <= (ambient_temp + CFG["ect_offset"])

    # CHEAT condition
    df["Engine Fault"] = (~df["TPS OK"]) & (~df["Lambda OK"]) & (~df["Fuel OK"])

    df["dt"] = df["Time (s)"].diff().fillna(0)

    cumul = 0
    cheat = False
    cheat_time = None

    for t, fault, dt in zip(df["Time (s)"], df["Engine Fault"], df["dt"]):
        if fault:
            cumul += dt
            if cumul >= CFG["cheat_delay"]:
                cheat = True
                cheat_time = t
                break
        else:
            cumul = 0

    # FAIL if any critical parameter false
    fail = (~df["TPS OK"] | ~df["Lambda OK"] | ~df["Fuel OK"] | ~df["ECT OK"]).any()

    display_cols = [
        "Time (s)",
        "TPS",
        "Lambda",
        "Fuel Pressure",
        "ECT",
        "TPS OK",
        "Lambda OK",
        "Fuel OK",
        "ECT OK",
        "Engine Fault"
    ]

    df = df[display_cols].round(2)

    return df, cheat, cheat_time, fail

# ================= ROUTES =================
@app.route("/")
def index():
    return render_template_string(HTML, table=None)

@app.route("/upload", methods=["POST"])
def upload():
    file = request.files["file"]
    location = request.form["location"]
    ambient_temp = float(request.form["ambient_temp"].replace(",", "."))

    df = load_link_csv(file)
    df, cheat, cheat_time, fail = analyze_dataframe(df, ambient_temp)

    if cheat:
        etat = f"CHEAT – début à {cheat_time:.2f} s"
        color = "text-danger"
    elif fail:
        etat = f"FAIL – Paramètre hors tolérance"
        color = "text-warning"
    else:
        etat = f"PASS | {location}"
        color = "text-success"

    fname = f"result_{datetime.now().timestamp()}.csv"
    path = os.path.join(UPLOAD_DIR, fname)
    df.to_csv(path, index=False)

    table = df.head(100).to_html(classes="table table-dark table-striped", index=False)

    return render_template_string(
        HTML,
        table=table,
        download=url_for("download", fname=fname),
        etat_global=etat,
        status_color=color
    )

@app.route("/download")
def download():
    return send_file(os.path.join(UPLOAD_DIR, request.args["fname"]), as_attachment=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)

