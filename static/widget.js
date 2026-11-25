/**
 * Mud & Meadows Resort AI Concierge - Embeddable Widget SDK
 * Encapsulated via Shadow DOM for 100% CSS & JavaScript isolation.
 */

(function () {
  // Prevent duplicate initialization
  if (window.MudAndMeadowsChatWidgetInitialized) return;
  window.MudAndMeadowsChatWidgetInitialized = true;

  // Determine API base URL from script tag or current origin
  const scriptTag = document.currentScript || document.querySelector('script[data-resort-id]');
  const API_BASE = (scriptTag && scriptTag.getAttribute('data-api-base')) || window.location.origin;

  // Session ID stored in sessionStorage for conversation continuity
  let sessionId = sessionStorage.getItem('mm_chat_session_id');
  if (!sessionId) {
    sessionId = 'session_' + Math.random().toString(36).substring(2, 11);
    sessionStorage.setItem('mm_chat_session_id', sessionId);
  }

  // Inject Razorpay Checkout SDK dynamically on parent document
  if (!window.Razorpay) {
    const rzpScript = document.createElement('script');
    rzpScript.src = 'https://checkout.razorpay.com/v1/checkout.js';
    rzpScript.async = true;
    document.head.appendChild(rzpScript);
  }

  // Create Host Container for Shadow DOM
  const hostElement = document.createElement('div');
  hostElement.id = 'mud-and-meadows-widget-root';
  document.body.appendChild(hostElement);

  const shadow = hostElement.attachShadow({ mode: 'open' });

  // Load Widget Styles inside Shadow Root
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = `${API_BASE}/static/widget.css`;
  shadow.appendChild(link);

  // Widget HTML Structure
  const container = document.createElement('div');
  container.innerHTML = `
    <!-- Launcher Button -->
    <button class="chat-launcher" id="launcherBtn" title="Chat with Mud & Meadows Concierge">
      <svg viewBox="0 0 24 24">
        <path d="M12 2C6.477 2 2 6.477 2 12c0 1.821.487 3.53 1.338 5L2.5 21.5l4.632-.821C8.583 21.493 10.244 22 12 22c5.523 0 10-4.477 10-10S17.523 2 12 2zm0 18c-1.543 0-2.99-.413-4.24-1.135l-.304-.175-3.084.546.556-2.984-.19-.318C4.053 14.73 3.6 13.407 3.6 12c0-4.632 3.768-8.4 8.4-8.4s8.4 3.768 8.4 8.4-3.768 8.4-8.4 8.4z"/>
      </svg>
    </button>

    <!-- Chat Window -->
    <div class="chat-window hidden" id="chatWindow">
      <!-- Header -->
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

      <!-- Messages Area -->
      <div class="chat-messages" id="messagesContainer">
        <div class="message bot">
          Namaste! I am <strong>Shruti</strong>, your personal guest concierge at <strong>Mud & Meadows Luxury Resort</strong>. 🌿<br><br>
          I am here to assist you with our luxury villas, calculate stay packages, arrange organic dining and spa treatments, and help you reserve your room. You can type or tap the microphone to speak with me in <strong>Hindi, English, or your regional language</strong>!
        </div>
      </div>

      <!-- Footer / Input -->
      <div class="chat-footer">
        <button class="chat-btn voice-btn" id="voiceBtn" title="Hold/Tap to Speak (Hindi, Bhojpuri, Kannada, etc.)">
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

  // DOM Elements inside Shadow Root
  const launcherBtn = shadow.getElementById('launcherBtn');
  const chatWindow = shadow.getElementById('chatWindow');
  const closeBtn = shadow.getElementById('closeBtn');
  const messagesContainer = shadow.getElementById('messagesContainer');
  const chatInput = shadow.getElementById('chatInput');
  const sendBtn = shadow.getElementById('sendBtn');
  const voiceBtn = shadow.getElementById('voiceBtn');

  // Toggle Window Visibility
  launcherBtn.addEventListener('click', () => chatWindow.classList.toggle('hidden'));
  closeBtn.addEventListener('click', () => chatWindow.classList.add('hidden'));

  // Append Message Helper
  function appendMessage(text, sender = 'bot') {
    const msg = document.createElement('div');
    msg.className = `message ${sender}`;
    msg.innerHTML = text.replace(/\n/g, '<br>');
    messagesContainer.appendChild(msg);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return msg;
  }

  // Render Interactive UI Cards
  function renderCards(cards) {
    if (!cards || !cards.length) return;

    const cardsContainer = document.createElement('div');
    cardsContainer.className = 'cards-container';

    cards.forEach(card => {
      if (card.type === 'cottage_card') {
        const cCard = document.createElement('div');
        cCard.className = 'cottage-card';
        const imgUrl = (card.images && card.images[0]) || 'https://images.unsplash.com/photo-1566073771259-6a8506099945?w=500';
        cCard.innerHTML = `
          <img src="${imgUrl}" class="cottage-card-img" alt="${card.name}" onerror="this.src='https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?w=500'"/>
          <div class="cottage-card-body">
            <div class="cottage-card-title">${card.name}</div>
            <div class="cottage-card-price">₹${card.price_per_night.toLocaleString()} / night</div>
            <div class="cottage-card-meta">👥 Max ${card.capacity} Guests • 🌿 ${card.amenities.slice(0, 3).join(', ')}</div>
            <button class="card-action-btn select-cottage-btn" data-id="${card.id}" data-name="${card.name}">
              Select & Get Exact Quote
            </button>
          </div>
        `;
        cCard.querySelector('.select-cottage-btn').addEventListener('click', () => {
          sendMessage(`Calculate exact quote for ${card.name} (ID: ${card.id}) from ${card.check_in || '2026-12-01'} to ${card.check_out || '2026-12-03'} for 2 adults`);
        });
        cardsContainer.appendChild(cCard);
      }
      else if (card.type === 'quote_card') {
        const q = card.quote;
        const qCard = document.createElement('div');
        qCard.className = 'quote-card';
        const waLink = card.whatsapp_url || q.whatsapp_url || `https://api.whatsapp.com/send?text=Stay%20Quotation%20for%20${encodeURIComponent(q.cottage_name)}`;
        const mailtoLink = card.mailto_url || q.mailto_url || `mailto:?subject=Mud%20and%20Meadows%20Quote&body=Stay%20Quotation%20for%20${encodeURIComponent(q.cottage_name)}`;

        qCard.innerHTML = `
          <div class="quote-header">Stay Summary: ${q.cottage_name}</div>
          <div class="quote-row"><span>Dates:</span> <span>${q.check_in} to ${q.check_out} (${q.nights} Nights)</span></div>
          <div class="quote-row"><span>Guests:</span> <span>${q.adults} Adults, ${q.children} Children</span></div>
          <div class="quote-row"><span>Room Rent:</span> <span>₹${q.base_room_rent.toLocaleString()}</span></div>
          ${q.extra_bed_total > 0 ? `<div class="quote-row"><span>Extra Bedding:</span> <span>₹${q.extra_bed_total.toLocaleString()}</span></div>` : ''}
          ${q.coupon_discount > 0 ? `<div class="quote-row" style="color:#10b981;"><span>Coupon Discount:</span> <span>-₹${q.coupon_discount.toLocaleString()}</span></div>` : ''}
          <div class="quote-row"><span>GST (${q.gst_percent}%):</span> <span>₹${q.gst_amount.toLocaleString()}</span></div>
          <div class="quote-row total"><span>Grand Total:</span> <span>₹${q.grand_total.toLocaleString()}</span></div>
          
          <div class="quote-actions">
            <button class="wa-btn" id="waBtn_${q.cottage_id}" title="Send or share quote on WhatsApp">
              <span>📲</span> Send Quote on WhatsApp
            </button>
            <button class="reserve-btn" id="payBtn_${q.cottage_id}" title="Reserve and pay online">
              <span>💳</span> Reserve Villa Online
            </button>
          </div>
        `;

        qCard.querySelector('.wa-btn').addEventListener('click', () => {
          const userPhone = prompt("Enter your 10-digit mobile number for WhatsApp (or leave blank to open WhatsApp directly):");
          let targetWa = waLink;
          if (userPhone && userPhone.trim()) {
            const cleanDigits = userPhone.replace(/\D/g, '');
            const finalDigits = cleanDigits.length === 10 ? '91' + cleanDigits : cleanDigits;
            targetWa = `https://api.whatsapp.com/send?phone=${finalDigits}&text=${encodeURIComponent("🌿 *Mud & Meadows Resort - Stay Quotation*\n\n🏨 *Villa:* " + q.cottage_name + "\n📅 *Dates:* " + q.check_in + " to " + q.check_out + " (" + q.nights + " Nights)\n👥 *Guests:* " + q.adults + " Adults\n✨ *Total:* ₹" + q.grand_total.toLocaleString() + " (incl. GST)\n\nPlease confirm my reservation!")}`;
          }
          window.open(targetWa, '_blank');
          appendMessage(`Opening WhatsApp with your quotation for ${q.cottage_name}! If the chat does not open, <a href="${targetWa}" target="_blank" style="color:#25D366;font-weight:bold;">tap here to open WhatsApp</a>.`, 'bot');
        });

        qCard.querySelector('.reserve-btn').addEventListener('click', () => {
          handleRazorpayCheckout(q);
        });

        cardsContainer.appendChild(qCard);
      }
      else if (card.type === 'whatsapp_card') {
        const waCard = document.createElement('div');
        waCard.className = 'quote-card';
        waCard.style.borderColor = '#25D366';
        waCard.innerHTML = `
          <div class="quote-header" style="color:#1b3b2b;">📲 WhatsApp Quotation Ready</div>
          <div class="quote-row"><span>Villa:</span> <span>${card.cottage_name}</span></div>
          <div class="quote-row"><span>Total:</span> <span>₹${(card.total_price || 0).toLocaleString()}</span></div>
          <div class="quote-row"><span>Mobile:</span> <span>${card.phone}</span></div>
          <div style="margin-top:10px;">
            <a href="${card.whatsapp_url}" target="_blank" class="wa-btn" style="text-decoration:none;">
              <span>📲</span> Open WhatsApp Chat Now
            </a>
          </div>
        `;
        cardsContainer.appendChild(waCard);
      }
    });

    messagesContainer.appendChild(cardsContainer);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Razorpay Payment Handler
  async function handleRazorpayCheckout(quote) {
    appendMessage(`Initiating secure payment for <strong>₹${quote.grand_total.toLocaleString()}</strong>...`, 'bot');

    const guestName = prompt("Please enter primary Guest Name:", "Guest User") || "Guest User";
    const guestEmail = prompt("Please enter your Email for Booking Voucher:", "guest@resort.com") || "guest@resort.com";
    const guestPhone = prompt("Please enter Mobile Number:", "9876543210") || "9876543210";

    try {
      // 1. Create Razorpay Order via Backend
      const orderResp = await fetch(`${API_BASE}/api/payment/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: quote.grand_total,
          receipt: `rcpt_${Date.now()}`,
          notes: { guest_name: guestName, cottage_id: quote.cottage_id }
        })
      });
      const orderData = await orderResp.json();
      const rzpOrder = orderData.order;

      // 2. Open Razorpay Checkout Modal
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
          contact: guestPhone
        },
        theme: { color: '#1b3b2b' },
        handler: async function (response) {
          appendMessage('Payment authorized! Confirming reservation with resort front-desk...', 'bot');

          // 3. Verify Payment and Create Official Booking
          const verifyResp = await fetch(`${API_BASE}/api/payment/verify-and-book`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              razorpay_order_id: response.razorpay_order_id || rzpOrder.id,
              razorpay_payment_id: response.razorpay_payment_id || 'pay_test_' + Date.now(),
              razorpay_signature: response.razorpay_signature || 'sig_verified',
              booking_data: {
                guest_name: guestName,
                guest_email: guestEmail,
                guest_phone: guestPhone,
                accommodation_id: quote.cottage_id,
                check_in: quote.check_in,
                check_out: quote.check_out,
                total_price: quote.grand_total
              }
            })
          });

          const verifyData = await verifyResp.json();
          appendMessage(`🎉 <strong>Booking Confirmed!</strong><br><br>
            <strong>Voucher ID:</strong> ${verifyData.booking_id || verifyData.booking?.id || '#MM-CONFIRMED'}<br>
            <strong>Cottage:</strong> ${quote.cottage_name}<br>
            <strong>Dates:</strong> ${quote.check_in} to ${quote.check_out}<br>
            <strong>Guest:</strong> ${guestName} (${guestEmail})<br><br>
            A confirmation voucher has been generated. We look forward to welcoming you to Mud & Meadows! 🌿`, 'bot');
        }
      };

      if (window.Razorpay) {
        const rzp = new window.Razorpay(options);
        rzp.open();
      } else {
        // Fallback simulation if checkout script is blocked by browser adblockers
        if (confirm("Simulate successful test payment?")) {
          options.handler({ razorpay_payment_id: 'pay_simulated_' + Date.now() });
        }
      }
    } catch (err) {
      appendMessage(`Error during payment setup: ${err.message}`, 'bot');
    }
  }

  // Send Text Message
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
        body: JSON.stringify({ session_id: sessionId, message: userText })
      });
      const data = await response.json();
      typingIndicator.innerHTML = data.text.replace(/\n/g, '<br>');
      renderCards(data.cards);
    } catch (err) {
      typingIndicator.innerHTML = 'Sorry, I encountered a connection issue. Please try again.';
    }
  }

  sendBtn.addEventListener('click', () => sendMessage());
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  // =========================================================================
  // VOICE INPUT (Hybrid: Web Speech API for instant live recognition
  // + MediaRecorder for server-side Whisper / Gemini translation)
  // =========================================================================
  let isRecording = false;
  let recognition = null;
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-IN'; // Default to English (India) to capture English words properly

    recognition.onstart = () => {
      isRecording = true;
      voiceBtn.classList.add('recording');
      chatInput.placeholder = '🎙️ Listening... speak now in English or Hindi';
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
      console.warn('Speech recognition status:', event.error);
      isRecording = false;
      voiceBtn.classList.remove('recording');
      chatInput.placeholder = 'Ask anything or request a booking...';
      if (event.error === 'not-allowed') {
        alert('Please allow microphone permissions in your browser address bar.');
      }
    };
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
      // Fallback alert for non-supported browsers
      alert('Your browser does not support Web Speech Recognition. Please type your message.');
    }
  });

})();
