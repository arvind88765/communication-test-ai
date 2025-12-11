from flask import Flask, render_template, request, jsonify, session, url_for, abort
from vosk import Model, KaldiRecognizer
import json
import wave
import os
import difflib
import uuid
import random
import shutil
import math

app = Flask(__name__)
app.secret_key = "super-secret-key-change-this"

# ----------------------------
# Load Sentences from JSON
# ----------------------------
DATASET_PATH = "sentences.json"
with open(DATASET_PATH, "r", encoding="utf-8") as f:
    DATASET = json.load(f)

READ_SENTENCES = DATASET.get("read_speak_sentences", [])
LISTEN_SENTENCES = DATASET.get("listen_speak_sentences", [])

# ----------------------------
# VOSK Model
# ----------------------------
MODEL_PATH = "vosk-model-small-en-us-0.15"
vosk_model = Model(MODEL_PATH)


# ---------------------------------
#  JARO SIMILARITY (for Pronunciation)
# ---------------------------------
def jaro_similarity(s1, s2):
    if s1 == s2:
        return 1.0

    len1, len2 = len(s1), len(s2)
    max_dist = math.floor(max(len1, len2) / 2) - 1

    match1 = [False] * len1
    match2 = [False] * len2

    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - max_dist)
        end = min(i + max_dist + 1, len2)
        for j in range(start, end):
            if not match2[j] and s1[i] == s2[j]:
                match1[i] = match2[j] = True
                matches += 1
                break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if match1[i]:
            while not match2[k]:
                k += 1
            if s1[i] != s2[k]:
                transpositions += 1
            k += 1

    transpositions /= 2

    return (
        (matches / len1)
        + (matches / len2)
        + ((matches - transpositions) / matches)
    ) / 3


# ---------------------------------
#  CONVERT AUDIO TO TEXT + DURATION
# ---------------------------------
def convert_audio_to_text(audio_path):
    wav_path = audio_path.replace(".webm", ".wav")

    os.system(f'ffmpeg -i "{audio_path}" -ar 16000 -ac 1 -y "{wav_path}"')

    wf = wave.open(wav_path, "rb")
    rate = wf.getframerate()
    frames = wf.getnframes()
    duration = frames / float(rate)

    rec = KaldiRecognizer(vosk_model, rate)
    rec.SetWords(True)

    text = ""
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if rec.AcceptWaveform(data):
            part = json.loads(rec.Result()).get("text", "")
            if part:
                text += " " + part

    final = json.loads(rec.FinalResult()).get("text", "")
    if final:
        text += " " + final

    return text.strip(), duration


# ---------------------------------
#  ADVANCED SCORING FUNCTIONS
# ---------------------------------
def score_pronunciation(reference, spoken):
    ref_words = reference.lower().split()
    spoken_words = spoken.lower().split()

    if not spoken_words:
        return 0.0

    sims = []
    for i, ref_word in enumerate(ref_words):
        if i < len(spoken_words):
            sims.append(jaro_similarity(ref_word, spoken_words[i]))
        else:
            sims.append(0)

    return round((sum(sims) / len(sims)) * 100, 2)


def score_fluency(reference, duration):
    word_count = len(reference.split())
    expected_time = word_count * 0.55  # seconds

    if duration <= 0:
        return 0.0

    ratio = expected_time / duration

    if ratio > 1:
        score = 100 - ((ratio - 1) * 25)
    else:
        score = ratio * 100

    return round(max(0, min(100, score)), 2)


def score_grammar(reference, spoken):
    ref_words = reference.lower().split()
    spoken_words = spoken.lower().split()

    if not spoken_words:
        return 0.0

    important = ref_words  # simple keyword grammar check
    correct = sum(1 for w in important if w in spoken_words)

    return round((correct / len(important)) * 100, 2)


def score_accuracy(reference, spoken):
    ref = reference.lower().strip()
    sp = spoken.lower().strip()
    if not sp:
        return 0.0
    return round(difflib.SequenceMatcher(None, ref, sp).ratio() * 100, 2)


def calculate_final_scores(reference, spoken, duration):
    pron = score_pronunciation(reference, spoken)
    flu = score_fluency(reference, duration)
    gram = score_grammar(reference, spoken)
    acc = score_accuracy(reference, spoken)

    final = (
        (pron * 0.30) +
        (flu * 0.25) +
        (gram * 0.25) +
        (acc * 0.20)
    )

    return {
        "pronunciation": pron,
        "fluency": flu,
        "grammar": gram,
        "accuracy": acc,
        "final": round(final, 2)
    }


# ----------------------------
# TEST START LOGIC
# ----------------------------
def start_test(mode, num_questions):

    if mode == "read":
        src = READ_SENTENCES
    else:
        src = LISTEN_SENTENCES

    num_questions = max(3, min(20, int(num_questions)))

    questions = random.sample(src, num_questions)

    session_id = uuid.uuid4().hex
    user_folder = os.path.join("uploads", f"user_{session_id}")
    os.makedirs(user_folder, exist_ok=True)

    session.update({
        "mode": mode,
        "questions": questions,
        "current_index": 0,
        "scores": [],
        "spoken_texts": [],
        "details": [],
        "user_folder": user_folder
    })

    return questions[0], 0, len(questions)


# ----------------------------
# ROUTES
# ----------------------------
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/choose-questions/<mode>")
def choose_questions(mode):
    return render_template("choose_questions.html", mode=mode)


@app.route("/start-test", methods=["POST"])
def start_test_route():
    mode = request.form.get("mode")
    qcount = int(request.form.get("question_count", 20))

    sentence, idx, total = start_test(mode, qcount)

    template = "read_speak.html" if mode == "read" else "listen_speak.html"
    return render_template(template, sentence=sentence, current_index=1, total_questions=total)


# ----------------------------
# EVALUATE (MAIN LOGIC)
# ----------------------------
@app.route("/evaluate", methods=["POST"])
def evaluate():
    questions = session["questions"]
    idx = session["current_index"]
    user_folder = session["user_folder"]

    audio = request.files["audio"]
    file_id = uuid.uuid4().hex
    audio_path = os.path.join(user_folder, f"{file_id}.webm")
    audio.save(audio_path)

    reference = questions[idx]

    spoken, duration = convert_audio_to_text(audio_path)
    try:
        os.remove(audio_path)
    except:
        pass

    scores = calculate_final_scores(reference, spoken, duration)

    session["details"].append({
        "question": reference,
        "spoken": spoken,
        "pronunciation": scores["pronunciation"],
        "fluency": scores["fluency"],
        "grammar": scores["grammar"],
        "accuracy": scores["accuracy"],
        "final": scores["final"]
    })

    idx += 1
    session["current_index"] = idx

    if idx >= len(questions):
        session["overall"] = round(
            sum(d["final"] for d in session["details"]) / len(session["details"]), 2
        )

        try:
            shutil.rmtree(user_folder)
        except:
            pass

        return jsonify({"done": True, "redirect_url": url_for("results")})

    next_sentence = questions[idx]
    return jsonify({
        "done": False,
        "current": idx + 1,
        "total": len(questions),
        "next_sentence": next_sentence
    })


# ----------------------------
# RESULTS PAGE
# ----------------------------
@app.route("/results")
def results():
    return render_template("result.html",
                           mode=session["mode"],
                           overall=session["overall"],
                           details=session["details"])


@app.route("/retry")
def retry():
    user_folder = session.get("user_folder")
    if user_folder:
        try:
            shutil.rmtree(user_folder)
        except:
            pass
    session.clear()
    return url_for("home")


if __name__ == "__main__":
    app.run(debug=True)
