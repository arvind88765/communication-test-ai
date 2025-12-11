let mediaRecorder = null;
let audioChunks = [];
let countdownInterval = null;
let timeLeft = 30;

// waveform visualizer
let audioCtx, analyser, dataArray, source;

function startWaveform(stream) {
  audioCtx = new AudioContext();
  analyser = audioCtx.createAnalyser();
  source = audioCtx.createMediaStreamSource(stream);
  source.connect(analyser);
  analyser.fftSize = 256;

  const bufferLength = analyser.frequencyBinCount;
  dataArray = new Uint8Array(bufferLength);

  const canvas = document.getElementById("waveform");
  const ctx = canvas.getContext("2d");

  function draw() {
    requestAnimationFrame(draw);
    analyser.getByteFrequencyData(dataArray);

    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    ctx.lineWidth = 2;
    ctx.strokeStyle = "#3b82f6";
    ctx.beginPath();

    const sliceWidth = canvas.width / bufferLength;
    let x = 0;

    for (let i = 0; i < bufferLength; i++) {
      const v = dataArray[i] / 128.0;
      const y = (v * canvas.height) / 2;

      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);

      x += sliceWidth;
    }

    ctx.stroke();
  }
  draw();
}

function stopWaveform() {
  if (audioCtx) audioCtx.close();
}

function setupTestPage(mode) {
  const startBtn = document.getElementById("startBtn");
  const stopBtn = document.getElementById("stopBtn");
  const submitBtn = document.getElementById("submitBtn");
  const playBtn = document.getElementById("playBtn");
  const statusEl = document.getElementById("status");
  const timerEl = document.getElementById("timer");
  const questionNumEl = document.getElementById("questionNumber");
  const totalQEl = document.getElementById("totalQuestions");
  const progressFill = document.getElementById("progressFill");
  const sentenceEl = document.getElementById("sentence");

  // Listen mode: play TTS
  if (playBtn && mode === "listen") {
    playBtn.addEventListener("click", () => {
      const text = sentenceEl.value;
      if ("speechSynthesis" in window) {
        speechSynthesis.speak(new SpeechSynthesisUtterance(text));
      } else {
        alert("Speech synthesis not supported.");
      }
    });
  }

  startBtn.addEventListener("click", async () => {
    timeLeft = 30;
    timerEl.textContent = timeLeft;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];

      startWaveform(stream);

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunks.push(e.data);
      };

      mediaRecorder.onstart = () => {
        statusEl.textContent = "Recording...";
        startBtn.disabled = true;
        stopBtn.disabled = false;

        countdownInterval = setInterval(() => {
          timeLeft -= 1;
          timerEl.textContent = timeLeft;
          if (timeLeft <= 0) stopRecording(stopBtn, statusEl);
        }, 1000);
      };

      mediaRecorder.onstop = () => {
        clearInterval(countdownInterval);
        stopWaveform();
        stopBtn.disabled = true;
        submitBtn.disabled = false;
        statusEl.textContent = "Recording complete. Submit when ready.";
      };

      mediaRecorder.start();
    } catch (err) {
      console.error(err);
      alert("Could not access microphone.");
      statusEl.textContent = "Microphone access denied.";
    }
  });

  stopBtn.addEventListener("click", () => {
    stopRecording(stopBtn, statusEl);
  });

  submitBtn.addEventListener("click", async () => {
    submitBtn.disabled = true;

    if (!audioChunks.length) {
      statusEl.textContent = "No audio recorded. Please record again.";
      submitBtn.disabled = false;
      return;
    }

    const blob = new Blob(audioChunks, { type: "audio/webm" });

    console.log("Blob size:", blob.size);
    console.log("Blob type:", blob.type);

    const formData = new FormData();
    formData.append("audio", blob);

    statusEl.textContent = "Processing your answer...";

    try {
      const res = await fetch("/evaluate", {
        method: "POST",
        body: formData
      });

      console.log("Response status:", res.status);

      if (!res.ok) {
        const text = await res.text();
        console.error("Server Error:", text);
        throw new Error("Server returned error");
      }

      const data = await res.json();
      console.log("Server JSON:", data);

      if (data.done) {
        statusEl.textContent = "Test completed. Showing results...";
        window.location.href = data.redirect_url;
        return;
      }

      // Load next question
      statusEl.textContent = "Next question loaded.";

      const total = data.total;
      const current = data.current;

      questionNumEl.textContent = current;
      progressFill.style.width = (current / total) * 100 + "%";

      if (sentenceEl.tagName.toLowerCase() === "p") {
        sentenceEl.textContent = data.next_sentence;
      } else {
        sentenceEl.value = data.next_sentence;
      }

      // reset for next recording
      audioChunks = [];
      submitBtn.disabled = true;
      startBtn.disabled = false;
      stopBtn.disabled = true;
      timeLeft = 30;
      timerEl.textContent = timeLeft;

    } catch (err) {
      console.error("Fetch error:", err);
      statusEl.textContent = "Error sending audio to server.";
      submitBtn.disabled = false;
    }
  });
}

function stopRecording(stopBtn, statusEl) {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
    statusEl.textContent = "Stopping...";
    stopBtn.disabled = true;
  }
}
