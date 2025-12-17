(function () {
  const DEBUG = true;

  let tg = null;
  let tgReady = false;
  let uiBound = false;

  function initTG() {
    // Проверяем разные способы доступа к Telegram Web App API
    if (window.Telegram && window.Telegram.WebApp) {
      tg = window.Telegram.WebApp;
      tgReady = true;
      try {
        tg.ready();
        tg.expand();
        console.log("Telegram WebApp API инициализирован успешно");
      } catch (e) {
        console.warn("TG init error:", e);
      }
    } else if (window.tg && window.tg.WebApp) {
      // Альтернативный способ доступа
      tg = window.tg.WebApp;
      tgReady = true;
      try {
        tg.ready();
        tg.expand();
        console.log("Telegram WebApp API инициализирован (альтернативный путь)");
      } catch (e) {
        console.warn("TG init error (alt):", e);
      }
    } else {
      tgReady = false;
      console.warn("Telegram WebApp API не найден. window.Telegram:", window.Telegram, "window.tg:", window.tg);
    }
  }

  // Пытаемся инициализировать сразу
  initTG();

  // Повторные попытки инициализации
  document.addEventListener("DOMContentLoaded", function() {
    setTimeout(initTG, 100); // Небольшая задержка для загрузки скрипта
  });
  window.addEventListener("focus", initTG);
  window.addEventListener("visibilitychange", function() {
    if (!document.hidden) {
      setTimeout(initTG, 100);
    }
  });

  let btnQR = null;
  let btnPhoto = null;
  let videoWrapper = null;
  let video = null;
  let captureBtn = null;
  let statusEl = null;
  let resultEl = null;
  let resultCodeEl = null;
  let btnSend = null;
  let btnRetry = null;

  function collectAuthInfo() {
    if (!tgReady || !tg) {
      return {};
    }
    const user = (tg.initDataUnsafe && tg.initDataUnsafe.user) || null;
    const initData = tg.initData || "";
    return {
      init_data: initData,
      user: user
        ? {
            id: user.id,
            username: user.username,
            first_name: user.first_name,
            last_name: user.last_name,
            language_code: user.language_code,
          }
        : null,
    };
  }

  let stream = null;
  let qrLoop = null;
  let lastCode = null;
  let mode = null;

  function setStatus(text, type = "info") {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = "status " + type;
    statusEl.style.display = "block";
  }

  function hideStatus() {
    if (!statusEl) return;
    statusEl.style.display = "none";
  }

  function stopCamera() {
    if (qrLoop) cancelAnimationFrame(qrLoop);
    qrLoop = null;

    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
    }
    stream = null;

    videoWrapper.style.display = "none";
    captureBtn.style.display = "none";
  }

  function showResult(code) {
    lastCode = code;
    resultCodeEl.textContent = code;
    resultEl.style.display = "block";
    hideStatus();
    stopCamera();
    sendToBot({ type: "code", data: code });
  }

  async function openCamera() {
    hideStatus();
    resultEl.style.display = "none";

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode: { ideal: "environment" },
          width: { ideal: 1280 },
          height: { ideal: 720 },
          focusMode: "continuous",
          advanced: [{ focusMode: "continuous" }],
        },
        audio: false,
      });

      video.srcObject = stream;
      try {
        await video.play();
      } catch (err) {
        console.warn("video.play() error:", err);
      }

      // Пробуем включить автофокус на треках, если поддерживается
      const [track] = stream.getVideoTracks();
      if (track && track.getCapabilities) {
        const caps = track.getCapabilities();
        const focusModeSupported = caps.focusMode && caps.focusMode.includes("continuous");
        if (focusModeSupported && track.applyConstraints) {
          try {
            await track.applyConstraints({ advanced: [{ focusMode: "continuous" }] });
            console.log("Автофокус активирован (continuous)");
          } catch (e) {
            console.warn("Не удалось включить автофокус:", e);
          }
        }
      }

      videoWrapper.style.display = "block";
      return true;
    } catch (e) {
      console.error("Camera error:", e);
      setStatus("Не удалось открыть камеру", "error");
      return false;
    }
  }

  function startQRLoop() {
    if (!window.jsQR) {
      setStatus("Модуль QR не загружен", "error");
      return;
    }

    setStatus("Наведите камеру на QR-код…", "success");

    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    function loop() {
      if (!video.videoWidth) {
        qrLoop = requestAnimationFrame(loop);
        return;
      }

      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;

      ctx.drawImage(video, 0, 0);

      try {
        const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(imageData.data, canvas.width, canvas.height, {
          inversionAttempts: "attemptBoth",
        });

        if (code && code.data) {
          showResult(code.data);
          return;
        }
      } catch (e) {
        console.warn("QR error:", e);
      }

      qrLoop = requestAnimationFrame(loop);
    }

    loop();
  }

  async function startQR() {
    mode = "qr";
    console.log("startQR");
    if (await openCamera()) {
      startQRLoop();
    } else {
      setStatus("Не удалось открыть камеру для сканирования", "error");
    }
  }

  async function startPhoto() {
    mode = "photo";
    if (await openCamera()) {
      captureBtn.style.display = "block";
      setStatus("Сделайте фото", "success");
    }
  }

  function sendToBot(payload) {
    // Повторная инициализация перед отправкой
    initTG();
    
    // Даем немного времени на инициализацию
    setTimeout(() => {
      // Проверяем доступность API
      if (!tg || !tg.sendData) {
        // Последняя попытка инициализации
        initTG();
        
        if (!tg || !tg.sendData) {
          setStatus("WebApp API недоступен! Проверьте, что Web App открыт через Telegram.", "error");
          console.error("TG API missing:", {
            tg: tg,
            hasTelegram: !!window.Telegram,
            hasWebApp: !!(window.Telegram && window.Telegram.WebApp),
            hasSendData: !!(tg && tg.sendData),
            userAgent: navigator.userAgent
          });
          return;
        }
      }

      const payloadInfo = {
        type: payload.type,
        dataPreview: typeof payload.data === "string" ? payload.data.slice(0, 50) : "<non-string>",
      };

      try {
        // Для фото проверяем размер base64 данных отдельно
        if (payload.type === "photo" && payload.data) {
          const base64Data = payload.data.includes(",") ? payload.data.split(",")[1] : payload.data;
          const estimatedSize = Math.ceil(base64Data.length * 3 / 4);
          
          if (estimatedSize > 50000) {
            setStatus("Ошибка: изображение слишком большое. Попробуйте сфотографировать ближе к тексту или используйте другой способ.", "error");
            console.error("Изображение слишком большое:", {
              base64Length: base64Data.length,
              estimatedSize: estimatedSize,
              estimatedSizeKB: (estimatedSize / 1024).toFixed(2)
            });
            return;
          }
        }
        
        // Добавляем минимальные метаданные для отладки (без роста размера)
        const augmentedPayload = {
          ...payload,
          auth: collectAuthInfo(),
          ts: Date.now(),
        };
        const dataStr = JSON.stringify(augmentedPayload);
        const dataSize = new Blob([dataStr]).size;
        const MAX_TG_BYTES = 3500; // фактический лимит sendData в Telegram WebApp ~4KB, берем с запасом
        console.log("Отправка данных в бот:", {
          ...payloadInfo,
          dataSize: dataSize,
          dataSizeKB: (dataSize / 1024).toFixed(2) + " KB",
          jsonLength: dataStr.length
        });
        
        // Проверяем размер JSON строки (Telegram ограничение ~4KB для sendData)
        if (dataSize > MAX_TG_BYTES || dataStr.length > MAX_TG_BYTES) {
          setStatus(
            "Ошибка: данные слишком большие для отправки (" +
              (dataSize / 1024).toFixed(2) +
              " KB). Сделайте фото ближе/четче или введите вручную.",
            "error"
          );
          console.error("Данные слишком большие:", {
            blobSize: dataSize,
            stringLength: dataStr.length,
            limitBytes: MAX_TG_BYTES
          });
          return;
        }
        
        // Проверяем, что JSON валидный
        try {
          JSON.parse(dataStr);
        } catch (e) {
          setStatus("Ошибка: неверный формат данных", "error");
          console.error("Невалидный JSON:", e);
          return;
        }
        const tgState = {
          hasTG: !!tg,
          hasSendData: !!(tg && tg.sendData),
          platform: tg && tg.platform,
          version: tg && tg.version,
          colorScheme: tg && tg.colorScheme,
        };

        try {
          console.log("Вызов tg.sendData", { ...tgState, ...payloadInfo, dataSize });
          setStatus("Отправляем данные в бот...", "info");
          tg.sendData(dataStr);
          setStatus("✅ Данные отправлены в бот", "success");
          console.log("sendData ok", { ...tgState, ...payloadInfo, dataSize, ua: navigator.userAgent });
        } catch (sendErr) {
          console.error("sendData threw:", sendErr, { ...tgState, ...payloadInfo });
          setStatus("Ошибка отправки данных: " + (sendErr.message || sendErr.toString()), "error");
          return;
        }
        
        // Закрываем Web App через задержку, чтобы отправка точно успела (оставляем больше времени для отладки)
        setTimeout(() => {
          try {
            if (tg && tg.close) {
              tg.close();
            }
          } catch (e) {
            console.warn("Ошибка при закрытии Web App:", e);
          }
        }, 8000);
      } catch (e) {
        console.error("Ошибка при отправке данных:", e);
        const errorMsg = e.message || e.toString();
        
        // Более детальная обработка ошибок
        if (errorMsg.includes("WebAppDataInvalid") || errorMsg.includes("Invalid")) {
          setStatus("Ошибка: неверный формат данных. Возможно, изображение слишком большое. Попробуйте сфотографировать ближе к тексту или используйте ручной ввод.", "error");
        } else if (errorMsg.includes("size") || errorMsg.includes("too large")) {
          setStatus("Ошибка: изображение слишком большое. Попробуйте сфотографировать ближе к тексту.", "error");
        } else {
          setStatus("Ошибка отправки: " + errorMsg, "error");
        }
      }
    }, 50);
  }

  function handleCaptureClick() {
    if (!video.videoWidth) return;

    const sourceWidth = video.videoWidth;
    const sourceHeight = video.videoHeight;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d");

    // Агрессивно ограничиваем размер, чтобы уложиться в ~4KB sendData
    const MAX_DIM = 200;
    const MIN_DIM = 120;
    const MAX_BYTES = 3200; // целимся чуть ниже лимита

    const scaleRatio = Math.min(MAX_DIM / sourceWidth, MAX_DIM / sourceHeight, 1);
    const startWidth = Math.max(MIN_DIM, Math.floor(sourceWidth * scaleRatio));
    const startHeight = Math.max(MIN_DIM, Math.floor(sourceHeight * scaleRatio));

    function attempt(quality, width, height, attemptNo = 1) {
      canvas.width = width;
      canvas.height = height;
      ctx.drawImage(video, 0, 0, width, height);

      setStatus(
        `Обработка фото (попытка ${attemptNo}, ${width}x${height}, q=${quality.toFixed(2)})`,
        "info"
      );

      canvas.toBlob(
        (blob) => {
          if (!blob) {
            setStatus("Ошибка при создании изображения", "error");
            return;
          }

          const reader = new FileReader();
          reader.onloadend = () => {
            const dataUrl = reader.result;
            const base64Data = dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
            const dataSize = Math.ceil(base64Data.length * 3 / 4); // примерный размер в байтах

            console.log("Размер изображения:", {
              attempt: attemptNo,
              blobSize: blob.size,
              base64Size: base64Data.length,
              estimatedDataSize: dataSize,
              quality,
              width,
              height,
            });

            if (
              dataSize > MAX_BYTES &&
              (quality > 0.08 || width > MIN_DIM || height > MIN_DIM) &&
              attemptNo < 6
            ) {
              const nextQuality = Math.max(0.08, quality - 0.05);
              const nextWidth = Math.max(MIN_DIM, Math.floor(width * 0.85));
              const nextHeight = Math.max(MIN_DIM, Math.floor(height * 0.85));
              console.log("Изображение большое, пробуем сжать сильнее", {
                nextQuality,
                nextWidth,
                nextHeight,
              });
              attempt(nextQuality, nextWidth, nextHeight, attemptNo + 1);
              return;
            }

            if (dataSize > MAX_BYTES) {
              setStatus(
                `Ошибка: изображение слишком большое (${(dataSize / 1024).toFixed(
                  2
                )} KB). Поднесите камеру ближе и попробуйте еще раз.`,
                "error"
              );
              return;
            }

            // Отправляем данные
            sendToBot({ type: "photo", data: dataUrl });
          };
          reader.onerror = () => {
            setStatus("Ошибка при чтении изображения", "error");
          };
          reader.readAsDataURL(blob);
        },
        "image/jpeg",
        quality
      );
    }

    attempt(0.25, startWidth, startHeight, 1);
  }

  function bindElements() {
    btnQR = document.getElementById("btn-qr");
    btnPhoto = document.getElementById("btn-photo");
    videoWrapper = document.getElementById("video-wrapper");
    video = document.getElementById("video");
    captureBtn = document.getElementById("capture-btn");
    statusEl = document.getElementById("status");
    resultEl = document.getElementById("result");
    resultCodeEl = document.getElementById("result-code");
    btnSend = document.getElementById("btn-send");
    btnRetry = document.getElementById("btn-retry");
    return btnQR && btnPhoto && videoWrapper && video && captureBtn && statusEl && resultEl && resultCodeEl && btnSend && btnRetry;
  }

  function bindHandlers() {
    btnSend.onclick = () => {
      if (lastCode) sendToBot({ type: "code", data: lastCode });
    };

    btnRetry.onclick = () => {
      resultEl.style.display = "none";
      setStatus("Выберите режим сканирования", "info");
    };

    btnQR.onclick = startQR;
    btnPhoto.onclick = startPhoto;

    if (captureBtn) {
      captureBtn.onclick = handleCaptureClick;
    } else {
      console.warn("captureBtn не найден при bindHandlers");
    }
  }

  function initUI() {
    console.log("initUI start, readyState:", document.readyState);
    if (!bindElements()) {
      console.error("Не удалось найти элементы UI для сканера");
      setStatus("UI не инициализировался. Обновите страницу.", "error");
      return;
    }
    uiBound = true;
    console.log("UI elements bound");
    bindHandlers();
    setStatus("Выберите режим сканирования", "info");
    window.addEventListener("beforeunload", stopCamera);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initUI);
  } else {
    initUI();
  }

  // Дополнительная попытка привязки через небольшую задержку (на случай кешей/ранней загрузки)
  setTimeout(() => {
    if (!uiBound || !btnQR || !btnPhoto) {
      console.warn("Повторная попытка initUI после задержки");
      initUI();
    }
  }, 500);

  // Глобальный обработчик ошибок, чтобы видеть их в статусе
  window.addEventListener("error", (e) => {
    console.error("Global error:", e.message, e.error);
    setStatus("Ошибка: " + e.message, "error");
  });
  window.addEventListener("unhandledrejection", (e) => {
    console.error("Unhandled rejection:", e.reason);
    setStatus("Ошибка: " + (e.reason && e.reason.message ? e.reason.message : e.reason), "error");
  });
})();
