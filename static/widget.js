/**
 * Mud & Meadows Resort AI Concierge - Embeddable Widget SDK
 * Encapsulated via Shadow DOM for strict CSS/DOM isolation and XSS safety.
 */

(function () {
  if (window.MudAndMeadowsChatWidgetInitialized) return;
  window.MudAndMeadowsChatWidgetInitialized = true;

  const scriptTag = document.currentScript || document.querySelector('script[data-resort-id]');
  const API_BASE = (scriptTag && scriptTag.getAttribute('data-api-base')) || window.location.origin;

  // Persistent cross-tab / returning visitor identifier stored in localStorage
  let sessionId = localStorage.getItem('mm_visitor_id') || sessionStorage.getItem('mm_chat_session_id');
  if (!sessionId) {
    sessionId = 'visitor_' + Math.random().toString(36).substring(2, 12) + '_' + Date.now().toString(36);
  }
  localStorage.setItem('mm_visitor_id', sessionId);

  let guestProfile = { name: '', email: '', phone: '' };

  function getDefaultDates() {
    const checkIn = new Date(Date.now() + 86400000);
    const checkOut = new Date(Date.now() + 3 * 86400000);
    return {
      checkIn: checkIn.toISOString().split('T')[0],
      checkOut: checkOut.toISOString().split('T')[0],
    };
  }

  if (!window.Razorpay) {
    const rzpScript = document.createElement('script');
    rzpScript.src = 'https://checkout.razorpay.com/v1/checkout.js';
    rzpScript.async = true;
    document.head.appendChild(rzpScript);
  }

  const hostElement = document.createElement('div');
  hostElement.id = 'mud-and-meadows-widget-root';
  document.body.appendChild(hostElement);

  const shadow = hostElement.attachShadow({ mode: 'open' });

  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `${API_BASE}/static/widget.css`;
  shadow.appendChild(link);

  const container = document.createElement('div');
  container.innerHTML = `
    <button class="chat-launcher" id="launcherBtn" title="Chat with Mud & Meadows Concierge">
      <svg viewBox="0 0 24 24">
        <path d="M12 2C6.477 2 2 6.477 2 12c0 1.821.487 3.53 1.338 5L2.5 21.5l4.632-.821C8.583 21.493 10.244 22 12 22c5.523 0 10-4.477 10-10S17.523 2 12 2zm0 18c-1.543 0-2.99-.413-4.24-1.135l-.304-.175-3.084.546.556-2.984-.19-.318C4.053 14.73 3.6 13.407 3.6 12c0-4.632 3.768-8.4 8.4-8.4s8.4 3.768 8.4 8.4-3.768 8.4-8.4 8.4z"/>
      </svg>
    </button>

    <div class="chat-window hidden" id="chatWindow">
      <div class="chat-header">
        <div class="chat-header-info">
          <div class="chat-avatar">S</div>
          <div class="chat-title">
            <h3>Shruti</h3>
            <p>Guest Concierge • Mud & Meadows</p>
          </div>
        </div>
        <button class="chat-close-btn" id="closeBtn" title="Close Chat">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="chat-messages" id="messagesContainer">
        <div class="message bot">
          Namaste! I am <strong>Shruti</strong>, your personal guest concierge at <strong>Mud &amp; Meadows Luxury Resort</strong>.<br><br>
          I can assist you with live villa availability, exact stay quotations with taxes, dining menus, and instant room reservations. Type or tap the microphone to speak in <strong>English or Hindi</strong>.
        </div>
      </div>

      <div class="chat-footer">
        <button class="chat-btn voice-btn" id="voiceBtn" title="Tap to Speak">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>
            <path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>
            <line x1="12" y1="19" x2="12" y2="23"></line>
            <line x1="8" y1="23" x2="16" y2="23"></line>
          </svg>
        </button>
        <input type="text" class="chat-input" id="chatInput" placeholder="Ask anything or request a booking..." autocomplete="off"/>
        <button class="chat-btn send-btn" id="sendBtn" title="Send message">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="22" y1="2" x2="11" y2="13"></line>
            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
          </svg>
        </button>
      </div>
    </div>
  `;
  shadow.appendChild(container);

  const launcherBtn = shadow.getElementById('launcherBtn');
  const chatWindow = shadow.getElementById('chatWindow');
  const closeBtn = shadow.getElementById('closeBtn');
  const messagesContainer = shadow.getElementById('messagesContainer');
  const chatInput = shadow.getElementById('chatInput');
  const sendBtn = shadow.getElementById('sendBtn');
  const voiceBtn = shadow.getElementById('voiceBtn');

  launcherBtn.addEventListener('click', () => chatWindow.classList.toggle('hidden'));
  closeBtn.addEventListener('click', () => chatWindow.classList.add('hidden'));

  // XSS-safe HTML escaper and lightweight markdown renderer
  function escapeHtml(unsafe) {
    return String(unsafe || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatSafeBotHtml(text) {
    return escapeHtml(text)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/\n/g, '<br>');
  }

  function appendMessage(text, sender = 'bot', isSafePreformattedHtml = false) {
    const msg = document.createElement('div');
    msg.className = `message ${sender}`;
    if (sender === 'user') {
      msg.textContent = text;
    } else if (isSafePreformattedHtml) {
      msg.innerHTML = text;
    } else {
      msg.innerHTML = formatSafeBotHtml(text);
    }
    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msg;
  }

  function buildWhatsAppShareUrl(q, phoneDigits) {
    const lines = [
      '*Mud & Meadows Resort - Stay Quotation*',
      '',
      `*Villa:* ${q.cottage_name}`,
      `*Dates:* ${q.check_in} to ${q.check_out} (${q.nights} Nights)`,
      `*Guests:* ${q.adults} Adults`,
      `*Total (incl. GST):* INR ${Number(q.grand_total).toLocaleString()}`,
      '',
      'Please confirm my reservation details.',
    ].join('\n');
    const encoded = encodeURIComponent(lines);
    if (phoneDigits) {
      return `https://api.whatsapp.com/send?phone=${encodeURIComponent(phoneDigits)}&text=${encoded}`;
    }
    return `https://api.whatsapp.com/send?text=${encoded}`;
  }

  function renderCards(cards) {
    if (!cards || !cards.length) return;

    const cardsContainer = document.createElement('div');
    cardsContainer.className = 'cards-container';

    cards.forEach(card => {
      if (card.type === 'cottage_card') {
        const cCard = document.createElement('div');
        cCard.className = 'cottage-card';
        const imgUrl = (card.images && card.images[0]) || 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=500';
        const safeName = escapeHtml(card.name);
        const safeAmenities = escapeHtml((card.amenities || []).slice(0, 3).join(', '));
        cCard.innerHTML = `
          <img src="${escapeHtml(imgUrl)}" class="cottage-card-img" alt="${safeName}" onerror="this.src='https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?w=500'"/>
          <div class="cottage-card-body">
            <div class="cottage-card-title">${safeName}</div>
            <div class="cottage-card-price">₹${Number(card.price_per_night).toLocaleString()} / night</div>
            <div class="cottage-card-meta">Max ${Number(card.capacity)} Guests • ${safeAmenities}</div>
            <button class="card-action-btn select-cottage-btn">
              Select &amp; Get Exact Quote
            </button>
          </div>
        `;
        cCard.querySelector('.select-cottage-btn').addEventListener('click', () => {
          const fallbackDates = getDefaultDates();
          sendMessage(`Calculate exact quote for ${card.name} (ID: ${card.id}) from ${card.check_in || fallbackDates.checkIn} to ${card.check_out || fallbackDates.checkOut} for 2 adults`);
        });
        cardsContainer.appendChild(cCard);
      }
      else if (card.type === 'quote_card') {
        const q = card.quote;
        const qCard = document.createElement('div');
        qCard.className = 'quote-card';
        const defaultWaLink = card.whatsapp_url || q.whatsapp_url || buildWhatsAppShareUrl(q, '');

        qCard.innerHTML = `
          <div class="quote-header">Stay Summary: ${escapeHtml(q.cottage_name)}</div>
          <div class="quote-row"><span>Dates:</span> <span>${escapeHtml(q.check_in)} to ${escapeHtml(q.check_out)} (${Number(q.nights)} Nights)</span></div>
          <div class="quote-row"><span>Guests:</span> <span>${Number(q.adults)} Adults, ${Number(q.children)} Children</span></div>
          <div class="quote-row"><span>Room Rent:</span> <span>₹${Number(q.base_room_rent).toLocaleString()}</span></div>
          ${q.extra_bed_total > 0 ? `<div class="quote-row"><span>Extra Bedding:</span> <span>₹${Number(q.extra_bed_total).toLocaleString()}</span></div>` : ''}
          ${q.coupon_discount > 0 ? `<div class="quote-row" style="color:#10b981;"><span>Coupon Discount:</span> <span>-₹${Number(q.coupon_discount).toLocaleString()}</span></div>` : ''}
          <div class="quote-row"><span>GST (${Number(q.gst_percent)}%):</span> <span>₹${Number(q.gst_amount).toLocaleString()}</span></div>
          <div class="quote-row total"><span>Grand Total:</span> <span>₹${Number(q.grand_total).toLocaleString()}</span></div>
          
          <div class="quote-actions">
            <button class="wa-btn">Send Quote on WhatsApp</button>
            <button class="reserve-btn">Reserve Villa Online</button>
          </div>

          <!-- Inline WhatsApp Drawer -->
          <div class="inline-drawer wa-drawer hidden">
            <label>WhatsApp Mobile Number (Optional)</label>
            <input type="tel" class="wa-phone-input" placeholder="10-digit number (leave blank to pick chat)"/>
            <div class="inline-drawer-actions">
              <button class="inline-submit-btn wa-theme wa-confirm-btn">Open WhatsApp</button>
              <button class="inline-cancel-btn wa-cancel-btn">Cancel</button>
            </div>
          </div>

          <!-- Inline Checkout Guest Details Drawer -->
          <div class="inline-drawer checkout-drawer hidden">
            <label>Guest Details for Reservation</label>
            <input type="text" class="guest-name-input" placeholder="Full Name (e.g. Adarsh Tiwari)" required/>
            <input type="email" class="guest-email-input" placeholder="Email for Voucher" required/>
            <input type="tel" class="guest-phone-input" placeholder="10-digit Mobile Number" required/>
            <div class="inline-drawer-actions">
              <button class="inline-submit-btn checkout-confirm-btn">Pay ₹${Number(q.grand_total).toLocaleString()}</button>
              <button class="inline-cancel-btn checkout-cancel-btn">Cancel</button>
            </div>
          </div>
        `;

        const waDrawer = qCard.querySelector('.wa-drawer');
        const checkoutDrawer = qCard.querySelector('.checkout-drawer');
        const waInput = qCard.querySelector('.wa-phone-input');
        const nameInput = qCard.querySelector('.guest-name-input');
        const emailInput = qCard.querySelector('.guest-email-input');
        const phoneInput = qCard.querySelector('.guest-phone-input');

        // Pre-populate saved returning guest contact preferences
        if (guestProfile.phone) waInput.value = guestProfile.phone;
        if (guestProfile.name) nameInput.value = guestProfile.name;
        if (guestProfile.email) emailInput.value = guestProfile.email;
        if (guestProfile.phone) phoneInput.value = guestProfile.phone;

        qCard.querySelector('.wa-btn').addEventListener('click', () => {
          checkoutDrawer.classList.add('hidden');
          waDrawer.classList.toggle('hidden');
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        });

        qCard.querySelector('.wa-cancel-btn').addEventListener('click', () => {
          waDrawer.classList.add('hidden');
        });

        qCard.querySelector('.wa-confirm-btn').addEventListener('click', () => {
          const rawPhone = waInput.value.trim();
          let targetWa = defaultWaLink;
          if (rawPhone) {
            const cleanDigits = rawPhone.replace(/\D/g, '');
            const finalDigits = cleanDigits.length === 10 ? '91' + cleanDigits : cleanDigits;
            targetWa = buildWhatsAppShareUrl(q, finalDigits);
            guestProfile.phone = cleanDigits;
            fetch(`${API_BASE}/api/guest/identify`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id: sessionId, phone: cleanDigits }),
            }).catch(() => {});
          }
          window.open(targetWa, '_blank');
          waDrawer.classList.add('hidden');
          appendMessage(
            `Opening WhatsApp with your quotation for <strong>${escapeHtml(q.cottage_name)}</strong>. If blocked by browser popup settings, <a href="${escapeHtml(targetWa)}" target="_blank" style="color:#25D366;font-weight:bold;">tap here to open WhatsApp</a>.`,
            'bot',
            true
          );
        });

        qCard.querySelector('.reserve-btn').addEventListener('click', () => {
          waDrawer.classList.add('hidden');
          checkoutDrawer.classList.toggle('hidden');
          messagesContainer.scrollTop = messagesContainer.scrollHeight;
        });

        qCard.querySelector('.checkout-cancel-btn').addEventListener('click', () => {
          checkoutDrawer.classList.add('hidden');
        });

        qCard.querySelector('.checkout-confirm-btn').addEventListener('click', () => {
          const guestName = nameInput.value.trim();
          const guestEmail = emailInput.value.trim();
          const guestPhone = phoneInput.value.trim();

          if (!guestName || !guestEmail || !guestEmail.includes('@') || guestPhone.replace(/\D/g, '').length < 10) {
            appendMessage('Please enter a valid full name, email address, and 10-digit phone number to proceed.', 'bot');
            return;
          }

          guestProfile = { name: guestName, email: guestEmail, phone: guestPhone };
          checkoutDrawer.classList.add('hidden');
          handleRazorpayCheckout(q, { guestName, guestEmail, guestPhone });
        });

        cardsContainer.appendChild(qCard);
      }
      else if (card.type === 'whatsapp_card') {
        const waCard = document.createElement('div');
        waCard.className = 'quote-card';
        waCard.style.borderColor = '#25D366';
        waCard.innerHTML = `
          <div class="quote-header" style="color:#1b3b2b;">WhatsApp Quotation Ready</div>
          <div class="quote-row"><span>Villa:</span> <span>${escapeHtml(card.cottage_name)}</span></div>
          <div class="quote-row"><span>Total:</span> <span>₹${Number(card.total_price || 0).toLocaleString()}</span></div>
          <div class="quote-row"><span>Mobile:</span> <span>${escapeHtml(card.phone)}</span></div>
          <div style="margin-top:10px;">
            <a href="${escapeHtml(card.whatsapp_url)}" target="_blank" class="wa-btn" style="text-decoration:none;">
              Open WhatsApp Chat Now
            </a>
          </div>
        `;
        cardsContainer.appendChild(waCard);
      }
    });

    messagesContainer.appendChild(cardsContainer);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  async function handleRazorpayCheckout(quote, guestInfo) {
    const { guestName, guestEmail, guestPhone } = guestInfo;
    appendMessage(`Preparing secure server-authoritative order for <strong>${escapeHtml(quote.cottage_name)}</strong>...`, 'bot', true);

    const bookingData = {
      guest_name: guestName,
      guest_email: guestEmail,
      guest_phone: guestPhone,
      accommodation_id: quote.cottage_id,
      check_in: quote.check_in,
      check_out: quote.check_out,
      total_price: quote.grand_total,
    };

    try {
      // Server computes authoritative amount from cottage_id + dates + GST
      const orderResp = await fetch(`${API_BASE}/api/payment/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          cottage_id: quote.cottage_id,
          check_in: quote.check_in,
          check_out: quote.check_out,
          adults: quote.adults || 2,
          children: quote.children || 0,
          extra_beds: quote.extra_beds || 0,
          coupon_code: quote.coupon_code || null,
          session_id: sessionId,
          booking_data: bookingData,
          receipt: `rcpt_${Date.now()}`,
          notes: { guest_name: guestName, cottage_id: quote.cottage_id },
        }),
      });

      const orderData = await orderResp.json();
      if (!orderResp.ok) {
        throw new Error(orderData.detail || 'Could not initiate payment order.');
      }

      const rzpOrder = orderData.order;

      const options = {
        key: orderData.key_id || 'rzp_test_placeholder',
        amount: rzpOrder.amount,
        currency: 'INR',
        name: 'Mud & Meadows Luxury Resort',
        description: `Booking for ${quote.cottage_name}`,
        order_id: rzpOrder.id,
        prefill: {
          name: guestName,
          email: guestEmail,
          contact: guestPhone,
        },
        theme: { color: '#1b3b2b' },
        handler: async function (response) {
          appendMessage('Payment authorized. Confirming reservation with front desk...', 'bot');

          const verifyResp = await fetch(`${API_BASE}/api/payment/verify-and-book`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id || rzpOrder.id,
              razorpay_payment_id: response.razorpay_payment_id || 'pay_test_' + Date.now(),
              razorpay_signature: response.razorpay_signature || 'sig_verified',
              booking_data: bookingData,
            }),
          });

          const verifyData = await verifyResp.json();
          if (!verifyResp.ok) {
            appendMessage(`Verification error: ${escapeHtml(verifyData.detail || 'Payment rejected')}`, 'bot');
            return;
          }

          const refId = escapeHtml(verifyData.booking_id || (verifyData.booking && verifyData.booking.id) || '#MM-CONFIRMED');
          appendMessage(
            `<strong>Booking Confirmed!</strong><br><br>
            <strong>Voucher ID:</strong> ${refId}<br>
            <strong>Cottage:</strong> ${escapeHtml(quote.cottage_name)}<br>
            <strong>Dates:</strong> ${escapeHtml(quote.check_in)} to ${escapeHtml(quote.check_out)}<br>
            <strong>Guest:</strong> ${escapeHtml(guestName)} (${escapeHtml(guestEmail)})<br><br>
            We look forward to welcoming you to Mud &amp; Meadows.`,
            'bot',
            true
          );
        },
      };

      if (window.Razorpay) {
        const rzp = new window.Razorpay(options);
        rzp.open();
      } else {
        appendMessage('Razorpay checkout script could not load. Please disable content blockers for checkout.', 'bot');
      }
    } catch (err) {
      appendMessage(`Payment setup interrupted: ${escapeHtml(err.message)}`, 'bot');
    }
  }

  async function sendMessage(text) {
    const userText = text || chatInput.value.trim();
    if (!userText) return;

    appendMessage(userText, 'user');
    chatInput.value = '';

    const typingIndicator = appendMessage('...', 'bot');

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId, message: userText }),
      });
      const data = await response.json();
      if (!response.ok) {
        typingIndicator.textContent = data.detail || 'Service temporarily busy. Please try again shortly.';
        return;
      }
      typingIndicator.innerHTML = formatSafeBotHtml(data.text);
      renderCards(data.cards);
    } catch (err) {
      typingIndicator.textContent = 'Connection error. Please verify your network and try again.';
    }
  }

  sendBtn.addEventListener('click', () => sendMessage());
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  // Voice Recognition via Web Speech API + MediaRecorder Backend Fallback (iOS/Firefox)
  let isRecording = false;
  let recognition = null;
  let mediaRecorder = null;
  let audioChunks = [];
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-IN';

    recognition.onstart = () => {
      isRecording = true;
      voiceBtn.classList.add('recording');
      chatInput.placeholder = 'Listening... speak in English or Hindi';
    };

    recognition.onresult = (event) => {
      let interimTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        interimTranscript += event.results[i][0].transcript;
      }
      chatInput.value = interimTranscript;
    };

    recognition.onend = () => {
      isRecording = false;
      voiceBtn.classList.remove('recording');
      chatInput.placeholder = 'Ask anything or request a booking...';
      const spokenText = chatInput.value.trim();
      if (spokenText) {
        sendMessage(spokenText);
      }
    };

    recognition.onerror = (event) => {
      isRecording = false;
      voiceBtn.classList.remove('recording');
      chatInput.placeholder = 'Ask anything or request a booking...';
      if (event.error === 'not-allowed') {
        appendMessage('Please allow microphone access in your browser settings to use voice input.', 'bot');
      }
    };
  }

  async function toggleMediaRecorderFallback() {
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      appendMessage('Voice recording is unsupported in this browser. Please type your message.', 'bot');
      return;
    }
    if (!isRecording) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunks = [];
        mediaRecorder = new MediaRecorder(stream);
        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data);
        };
        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach((t) => t.stop());
          const blob = new Blob(audioChunks, { type: 'audio/webm' });
          const formData = new FormData();
          formData.append('audio', blob, 'voice.webm');
          formData.append('session_id', sessionId);
          const indicator = appendMessage('Transcribing voice note...', 'bot');
          try {
            const resp = await fetch(`${API_BASE}/api/voice/process`, { method: 'POST', body: formData });
            const data = await resp.json();
            if (resp.ok && data.agent_response) {
              indicator.remove();
              appendMessage(data.transcription, 'user');
              appendMessage(data.agent_response.text, 'bot');
              renderCards(data.agent_response.cards);
            } else {
              indicator.textContent = data.detail || 'Could not transcribe voice note.';
            }
          } catch (err) {
            indicator.textContent = 'Voice upload failed. Please type your inquiry.';
          }
        };
        mediaRecorder.start();
        isRecording = true;
        voiceBtn.classList.add('recording');
        chatInput.placeholder = 'Recording voice... tap mic again to send';
      } catch (err) {
        appendMessage('Microphone access denied. Please allow permission in browser settings.', 'bot');
      }
    } else if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      isRecording = false;
      voiceBtn.classList.remove('recording');
      chatInput.placeholder = 'Ask anything or request a booking...';
    }
  }

  voiceBtn.addEventListener('click', () => {
    if (recognition) {
      if (!isRecording) {
        try {
          recognition.start();
        } catch (e) {
          console.warn('Recognition start exception:', e);
        }
      } else {
        recognition.stop();
      }
    } else {
      toggleMediaRecorderFallback();
    }
  });

  // Restore visual chat history & returning visitor profile on page navigation
  (async function hydrateSession() {
    try {
      const resp = await fetch(`${API_BASE}/api/chat/history?session_id=${encodeURIComponent(sessionId)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (data.guest_profile) {
        guestProfile = {
          name: data.guest_profile.name || '',
          email: data.guest_profile.email || '',
          phone: data.guest_profile.phone || '',
        };
      }
      if (Array.isArray(data.messages) && data.messages.length > 0) {
        messagesContainer.innerHTML = '';
        data.messages.forEach((m) => appendMessage(m.text, m.role === 'user' ? 'user' : 'bot'));
      } else if (guestProfile.name) {
        appendMessage(`Welcome back to Mud & Meadows, **${guestProfile.name}**! Let me know if you'd like to continue exploring stays.`, 'bot');
      }
    } catch (e) {
      // Offline or first load gracefully falls back to default welcome bubble
    }
  })();
})();
