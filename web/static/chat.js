(() => {
  const chat = document.querySelector("#chat-scroll");
  const input = document.querySelector("#message-input");
  const sendButton = document.querySelector("#send-button");
  const receiptButton = document.querySelector("#receipt-button");
  const receiptDialog = document.querySelector("#receipt-dialog");
  const receiptForm = document.querySelector("#receipt-form");
  const receiptReference = document.querySelector("#receipt-reference");
  const receiptAmount = document.querySelector("#receipt-amount");
  const receiptAmountHint = document.querySelector("#receipt-amount-hint");
  const receiptDate = document.querySelector("#receipt-date");
  const referenceHint = document.querySelector("#reference-hint");
  const typingIndicator = document.querySelector("#typing-indicator");
  const suggestions = document.querySelector(".quick-prompts");
  const customerIdKey = "rifachat-demo-customer";
  const customerId = sessionStorage.getItem(customerIdKey) || newCustomerId();
  let busy = false;

  sessionStorage.setItem(customerIdKey, customerId);
  setToday();

  document.querySelector("#reset-chat").addEventListener("click", resetConversation);

  document.querySelector("#close-dialog").addEventListener("click", () => receiptDialog.close());
  receiptButton.addEventListener("click", openReceiptDialog);
  receiptForm.addEventListener("submit", submitReceipt);
  sendButton.addEventListener("click", () => sendMessage());
  input.addEventListener("input", resizeInput);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  suggestions.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-prompt]");
    if (!button) return;
    input.value = button.dataset.prompt;
    resizeInput();
    sendMessage();
  });

  function setToday() {
    const now = new Date();
    const localToday = new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
      .toISOString()
      .slice(0, 10);
    receiptDate.value = localToday;
    receiptDate.max = localToday;
  }

  function newCustomerId() {
    return `demo-${crypto.randomUUID().replace(/-/g, "")}`;
  }

  function openReceiptDialog() {
    const reference = [...chat.querySelectorAll(".message-bubble")]
      .map((bubble) => bubble.textContent.match(/\bDEMO-[A-F0-9]{12}\b/i))
      .find(Boolean)?.[0];
    const ticketValue = [...chat.querySelectorAll(".message-row.outgoing .message-bubble")]
      .reverse()
      .map((bubble) => bubble.textContent.match(/(?:\$\s*|(?:por|de|valor)\s+\$?)(\d+(?:[.,]\d{1,2})?)/i)?.[1])
      .find(Boolean);
    receiptReference.value = reference || "";
    receiptAmount.value = ticketValue ? ticketValue.replace(",", ".") : "";
    referenceHint.textContent = reference
      ? "Referencia tomada de los mensajes de esta conversación."
      : "Aparta un número primero para ver tu referencia.";
    receiptAmountHint.textContent = ticketValue
      ? `El comprobante debe coincidir exactamente con el valor elegido: $${receiptAmount.value} dólares.`
      : "El comprobante debe coincidir exactamente con el valor del boleto, en dólares.";
    receiptDialog.showModal();
  }

  function submitReceipt(event) {
    event.preventDefault();
    if (!receiptForm.reportValidity()) return;
    const receipt = {
      reference: receiptReference.value.trim(),
      amount: receiptAmount.value.trim(),
      date: receiptDate.value,
    };
    receiptDialog.close();
    sendMessage("Adjunto un comprobante de prueba.", receipt);
  }

  async function resetConversation() {
    const resetButton = document.querySelector("#reset-chat");
    resetButton.disabled = true;
    try {
      const response = await fetch("/api/conversations/reset", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ from_number: customerId }),
      });
      if (!response.ok) {
        appendMessage("incoming", `No se pudo reiniciar la conversación (${response.status}).`);
        return;
      }
      sessionStorage.setItem(customerIdKey, newCustomerId());
      window.location.reload();
    } catch {
      appendMessage("incoming", "No se pudo conectar con el servidor para reiniciar la conversación.");
    } finally {
      resetButton.disabled = false;
    }
  }

  async function sendMessage(textOverride, receipt) {
    if (busy) return;
    const text = (textOverride ?? input.value).trim();
    if (!text && !receipt) {
      input.focus();
      return;
    }

    if (!textOverride && !receipt) input.value = "";
    resizeInput();
    suggestions.hidden = true;
    appendMessage("outgoing", text || "Comprobante de prueba", receipt);
    setBusy(true);

    try {
      const response = await fetch("/webhook/whatsapp", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          from_number: customerId,
          text,
          image_attached: Boolean(receipt),
          ...(receipt ? { simulated_receipt: receipt } : {}),
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        const detail = formatError(result.detail);
        appendMessage("incoming", `No se pudo procesar el mensaje (${response.status}): ${detail}`);
      } else {
        appendMessage("incoming", result.reply);
      }
    } catch {
      appendMessage("incoming", "No se pudo conectar con el servidor. Comprueba que la aplicación siga activa e inténtalo de nuevo.");
    } finally {
      setBusy(false);
    }
  }

  function appendMessage(direction, text, receipt) {
    const row = document.createElement("div");
    row.className = `message-row ${direction}`;
    if (direction === "incoming") {
      const avatar = document.createElement("span");
      avatar.className = "bot-avatar";
      avatar.setAttribute("aria-hidden", "true");
      avatar.textContent = "R";
      row.append(avatar);
    }

    const content = document.createElement("div");
    content.className = "message-content";
    if (receipt) content.append(createReceiptAttachment(receipt));

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    addTextWithTicketLinks(bubble, text);
    content.append(bubble);

    const time = document.createElement("span");
    time.className = "message-time";
    time.textContent = `${direction === "incoming" ? "Asistente" : "Tú"} · ${new Intl.DateTimeFormat("es-MX", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date())}`;
    content.append(time);
    row.append(content);
    chat.insertBefore(row, typingIndicator);
    scrollToBottom();
  }

  function createReceiptAttachment(receipt) {
    const attachment = document.createElement("div");
    attachment.className = "receipt-attachment";
    const icon = document.createElement("span");
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = "▧";
    const details = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = "Comprobante de prueba";
    const summary = document.createElement("small");
    summary.textContent = `Referencia ${receipt.reference} · $${receipt.amount} dólares`;
    details.append(title, summary);
    attachment.append(icon, details);
    return attachment;
  }

  function addTextWithTicketLinks(container, text) {
    const ticketPattern = /\[(?:[^\]]+)\]\((?:\[[^\]]+\]\()?((?:https?:\/\/[^/\s)]+)?\/api\/tickets\/[a-f0-9-]+\.html)(?:\))?\)|(https?:\/\/[^/\s]+\/api\/tickets\/[a-f0-9-]+\.html|\/api\/tickets\/[a-f0-9-]+\.html)/gi;
    let cursor = 0;
    for (const match of text.matchAll(ticketPattern)) {
      container.append(document.createTextNode(text.slice(cursor, match.index)));
      const ticketUrl = match[1] || match[2];
      const url = new URL(ticketUrl, window.location.origin);
      if (url.origin !== window.location.origin) {
        container.append(document.createTextNode(match[0]));
      } else {
        const link = document.createElement("a");
        link.className = "ticket-link";
        link.href = url.href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.textContent = "↓ Ver ticket original Bonanza";
        container.append(link);
      }
      cursor = match.index + match[0].length;
    }
    container.append(document.createTextNode(text.slice(cursor)));
  }

  function formatError(detail) {
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = detail
        .map((issue) => typeof issue.msg === "string" ? issue.msg : "")
        .filter(Boolean);
      if (messages.length) return `Revisa los datos enviados: ${messages.join("; ")}`;
    }
    return "Revisa los datos del mensaje e inténtalo de nuevo.";
  }

  function setBusy(value) {
    busy = value;
    sendButton.disabled = value;
    input.disabled = value;
    receiptButton.disabled = value;
    typingIndicator.hidden = !value;
    if (value) scrollToBottom();
    else input.focus();
  }

  function resizeInput() {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      chat.scrollTop = chat.scrollHeight;
    });
  }
})();
