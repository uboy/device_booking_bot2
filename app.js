(function () {
  let tg = null;
  let tgReady = false;

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

  const btnQR = document.getElementById("btn-qr");
  const btnPhoto = document.getElementById("btn-photo");
  const videoWrapper = document.getElementById("video-wrapper");
  const video = document.getElementById("video");
  const captureBtn = document.getElementById("capture-btn");
  const statusEl = document.getElementById("status");
  const resultEl = document.getElementById("result");
  const resultCodeEl = document.getElementById("result-code");
  const btnSend = document.getElementById("btn-send");
  const btnRetry = document.getElementById("btn-retry");

  let stream = null;
  let qrLoop = null;
  let lastCode = null;
  let mode = null;

  function setStatus(text, type = "info") {
    statusEl.textContent = text;
    statusEl.className = "status " + type;
    statusEl.style.display = "block";
  }

  function hideStatus() {
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
  }

  async function openCamera() {
    hideStatus();
    resultEl.style.display = "none";

    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment" },
      });

      video.srcObject = stream;
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
        const code = jsQR(imageData.data, canvas.width, canvas.height);

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
    if (await openCamera()) startQRLoop();
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
        
        const dataStr = JSON.stringify(payload);
        const dataSize = new Blob([dataStr]).size;
        console.log("Отправка данных в бот:", {
          type: payload.type,
          dataSize: dataSize,
          dataSizeKB: (dataSize / 1024).toFixed(2) + " KB",
          jsonLength: dataStr.length
        });
        
        // Проверяем размер JSON строки (Telegram ограничение ~64KB для sendData)
        if (dataSize > 60000 || dataStr.length > 80000) {
          setStatus("Ошибка: данные слишком большие (" + (dataSize / 1024).toFixed(2) + " KB). Попробуйте сфотографировать ближе к тексту.", "error");
          console.error("Данные слишком большие:", {
            blobSize: dataSize,
            stringLength: dataStr.length
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
        
        tg.sendData(dataStr);
        setStatus("✅ Данные отправлены в бот", "success");
        
        // Закрываем Web App через небольшую задержку
        setTimeout(() => {
          try {
            if (tg && tg.close) {
              tg.close();
            }
          } catch (e) {
            console.warn("Ошибка при закрытии Web App:", e);
          }
        }, 500);
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

  captureBtn.onclick = () => {
    if (!video.videoWidth) return;

    const canvas = document.createElement("canvas");
    // Ограничиваем максимальный размер для уменьшения объема данных
    // Уменьшаем еще больше для Web App API
    const maxWidth = 800;
    const maxHeight = 800;
    let width = video.videoWidth;
    let height = video.videoHeight;
    
    // Масштабируем, если изображение слишком большое
    if (width > maxWidth || height > maxHeight) {
      const ratio = Math.min(maxWidth / width, maxHeight / height);
      width = Math.floor(width * ratio);
      height = Math.floor(height * ratio);
    }
    
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, width, height);

    setStatus("Обработка фото…", "info");

    // Функция для попытки отправки с разным качеством
    function trySendWithQuality(quality, maxAttempts = 3) {
      canvas.toBlob(
        (blob) => {
          if (!blob) {
            setStatus("Ошибка при создании изображения", "error");
            return;
          }
          
          const reader = new FileReader();
          reader.onloadend = () => {
            const dataUrl = reader.result;
            // Удаляем префикс для проверки размера
            const base64Data = dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
            const dataSize = Math.ceil(base64Data.length * 3 / 4); // Примерный размер в байтах
            
            console.log("Размер изображения:", {
              blobSize: blob.size,
              base64Size: base64Data.length,
              estimatedDataSize: dataSize,
              quality: quality
            });
            
            // Проверяем размер (Telegram ограничение ~64KB, но base64 увеличивает размер)
            // Безопасный лимит для base64: ~45KB исходных данных = ~60KB base64
            if (dataSize > 45000 && quality > 0.3 && maxAttempts > 0) {
              // Пробуем еще меньше качество
              const newQuality = Math.max(0.3, quality - 0.2);
              console.log("Изображение слишком большое, пробуем качество:", newQuality);
              trySendWithQuality(newQuality, maxAttempts - 1);
              return;
            }
            
            if (dataSize > 60000) {
              setStatus("Ошибка: изображение слишком большое даже после сжатия. Попробуйте сфотографировать ближе к тексту.", "error");
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
    
    // Начинаем с качества 0.6
    trySendWithQuality(0.6);
  };

  btnSend.onclick = () => {
    if (lastCode) sendToBot({ type: "code", data: lastCode });
  };

  btnRetry.onclick = () => {
    resultEl.style.display = "none";
    setStatus("Выберите режим сканирования", "info");
  };

  btnQR.onclick = startQR;
  btnPhoto.onclick = startPhoto;

  window.addEventListener("beforeunload", stopCamera);
})();
