// Client-side script for Gaming POS web app with SweetAlert + dynamic pricing

let currentUser = null;
let gamesList = [];
let sessionsList = [];
let stationsStatus = {};
let selectedSessionId = null;

function formatDuration(startISO) {
  try {
    const start = new Date(startISO);
    const now = new Date();
    let diffMs = now - start;
    if (diffMs < 0) diffMs = 0;
    const mins = Math.floor(diffMs / 60000);
    const hrs = Math.floor(mins / 60);
    const rem = mins % 60;
    return `${hrs}h ${rem}m`;
  } catch (e) {
    return '';
  }
}

function loadGames() {
  fetch('/api/games')
    .then(res => res.json())
    .then(data => {
      gamesList = data;
      const gameSelect = document.getElementById('game-select');
      gameSelect.innerHTML = '';
      data.forEach(game => {
        const opt = document.createElement('option');
        opt.value = game.name;
        opt.textContent = `${game.name} (₹${game.price_per_hour}/h)`;
        opt.dataset.requiresControllers = game.requires_controllers;
        gameSelect.appendChild(opt);
      });

      const controllerSelect = document.getElementById('controller-select');
      controllerSelect.innerHTML = '';
      for (let i = 1; i <= 4; i++) {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = i;
        controllerSelect.appendChild(opt);
      }

      onGameChange();

      // Also render admin price editing UI if present
      const adminDiv = document.getElementById('game-admin');
      if (adminDiv) {
        adminDiv.innerHTML = '';
        data.forEach(game => {
          const p = document.createElement('p');
          p.textContent = `${game.name} — ₹${game.price_per_hour}/h `;
          const btn = document.createElement('button');
          btn.textContent = 'Edit Price';
          btn.className = 'btn secondary';
          btn.onclick = () => promptUpdateGamePrice(game.name, game.price_per_hour);
          p.appendChild(btn);
          adminDiv.appendChild(p);
        });
      }
    })
    .catch(err => {
      console.error('Failed to load games', err);
      Swal.fire({ icon: 'error', title: 'Error', text: 'Failed to load games' });
    });
}

function refreshAll() {
  fetch('/api/stations')
    .then(res => res.json())
    .then(stations => {
      stationsStatus = stations;
      populateStationSelect();
      return fetch('/api/sessions');
    })
    .then(res => res.json())
    .then(data => {
      sessionsList = data;
      renderSessions();
    })
    .catch(err => {
      console.error('Failed to refresh', err);
      Swal.fire({ icon: 'error', title: 'Error', text: 'Failed to refresh sessions or stations' });
    });
}

function populateStationSelect() {
  const select = document.getElementById('station-select');
  const letters = ['A','B','C','D','E','F','G'];
  select.innerHTML = '';
  letters.forEach(letter => {
    const opt = document.createElement('option');
    opt.value = letter;
    opt.textContent = letter;
    if (stationsStatus[letter] && stationsStatus[letter].occupied) {
      opt.disabled = true;
    }
    select.appendChild(opt);
  });
}

function loadUser() {
  const mobile = document.getElementById('mobile-input').value.trim();
  if (!mobile) {
    Swal.fire({ icon: 'warning', title: 'Oops', text: 'Please enter a mobile number' });
    return;
  }
  fetch(`/api/users/${encodeURIComponent(mobile)}`)
    .then(res => res.json())
    .then(user => {
      currentUser = user;
      document.getElementById('user-mobile').textContent = user.mobile;
      document.getElementById('user-wallet').textContent = user.wallet.toFixed(2);
      document.getElementById('user-details').classList.remove('hidden');
      document.getElementById('session-section').classList.remove('hidden');
      document.getElementById('use-wallet-checkbox').checked = true;
    })
    .catch(err => {
      console.error('Failed to load user', err);
      Swal.fire({ icon: 'error', title: 'Error', text: 'Failed to load user' });
    });
}

function onGameChange() {
  const gameSelect = document.getElementById('game-select');
  const selectedOption = gameSelect.options[gameSelect.selectedIndex];
  const requiresControllers = selectedOption ? (selectedOption.dataset.requiresControllers === 'true') : true;
  const controllersRow = document.getElementById('controllers-row');
  if (requiresControllers) {
    controllersRow.classList.remove('hidden');
  } else {
    controllersRow.classList.add('hidden');
  }
}

function startSession() {
  if (!currentUser) {
    Swal.fire({ icon: 'warning', title: 'Oops', text: 'Please load a user first' });
    return;
  }
  const station = document.getElementById('station-select').value;
  const game = document.getElementById('game-select').value;
  const controllersVisible = !document.getElementById('controllers-row').classList.contains('hidden');
  const controllers = controllersVisible ? parseInt(document.getElementById('controller-select').value) : 0;
  const payload = { mobile: currentUser.mobile, station, game, controllers };
  fetch('/api/start_session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(resp => {
      if (resp.error) {
        Swal.fire({ icon: 'error', title: 'Error', text: resp.error });
      } else {
        refreshAll();
      }
    })
    .catch(err => {
      console.error('Failed to start session', err);
      Swal.fire({ icon: 'error', title: 'Error', text: 'Could not start session' });
    });
}

function renderSessions() {
  const container = document.getElementById('sessions-list');
  if (!sessionsList || sessionsList.length === 0) {
    container.innerHTML = '<p>No active sessions.</p>';
    return;
  }
  const table = document.createElement('table');
  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  ['Station','Mobile','Game','Controllers','Start Time','Duration','Actions'].forEach(text => {
    const th = document.createElement('th');
    th.textContent = text;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  const tbody = document.createElement('tbody');
  sessionsList.forEach(sess => {
    const tr = document.createElement('tr');
    const startLocal = new Date(sess.start_time).toLocaleString();
    const duration = formatDuration(sess.start_time);
    [sess.station, sess.mobile, sess.game, sess.controllers || '', startLocal, duration].forEach(val => {
      const td = document.createElement('td');
      td.textContent = val;
      tr.appendChild(td);
    });
    const actionsTd = document.createElement('td');
    const endBtn = document.createElement('button');
    endBtn.textContent = 'End';
    endBtn.className = 'btn danger';
    endBtn.addEventListener('click', () => openModal(sess.session_id));
    actionsTd.appendChild(endBtn);
    tr.appendChild(actionsTd);
    tbody.appendChild(tr);
  });
  table.appendChild(thead);
  table.appendChild(tbody);
  container.innerHTML = '';
  container.appendChild(table);
}

function openModal(sessionId) {
  selectedSessionId = sessionId;
  const sess = sessionsList.find(s => s.session_id === sessionId);
  if (!sess) return;
  const info = `Station ${sess.station} – ${sess.game} for ${sess.mobile}`;
  document.getElementById('modal-session-info').textContent = info;
  document.getElementById('food-cost-input').value = '0';
  document.getElementById('modal-use-wallet-checkbox').checked = true;
  document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  selectedSessionId = null;
}

function confirmEndSession() {
  if (!selectedSessionId) {
    closeModal();
    return;
  }
  const foodCost = parseFloat(document.getElementById('food-cost-input').value || '0');
  const useWallet = document.getElementById('modal-use-wallet-checkbox').checked;
  const payload = { session_id: selectedSessionId, food_cost: foodCost, use_wallet: useWallet };
  fetch('/api/end_session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(resp => {
      if (resp.error) {
        Swal.fire({ icon: 'error', title: 'Error', text: resp.error });
      } else {
        closeModal();
        if (currentUser && currentUser.mobile === resp.invoice.mobile) {
          currentUser.wallet = resp.invoice.remaining_wallet;
          document.getElementById('user-wallet').textContent = currentUser.wallet.toFixed(2);
        }
        refreshAll();
        const inv = resp.invoice;
        const msg = `Gaming Cost: ₹${inv.base_cost.toFixed(2)}\n` +
                    `Food Cost: ₹${inv.food_cost.toFixed(2)}\n` +
                    `Total Due: ₹${inv.total_due.toFixed(2)}\n` +
                    `Loyalty Earned (on gaming only): ₹${inv.loyalty_earned.toFixed(2)}\n` +
                    `Wallet Remaining: ₹${inv.remaining_wallet.toFixed(2)}`;
        Swal.fire({ icon: 'info', title: 'Invoice', text: msg });
        if (resp.pdf) {
          window.open(resp.pdf, '_blank');
        }
      }
    })
    .catch(err => {
      console.error('Failed to end session', err);
      Swal.fire({ icon: 'error', title: 'Error', text: 'Failed to end session' });
    });
}

// Prompt UI for updating price
function promptUpdateGamePrice(gameName, currentPrice) {
  Swal.fire({
    title: `Set new price for ${gameName}`,
    input: 'number',
    inputLabel: 'Price per hour',
    inputValue: currentPrice,
    showCancelButton: true,
    inputValidator: (value) => {
      if (!value || isNaN(value) || Number(value) <= 0) {
        return 'Please enter a valid positive price';
      }
      return null;
    }
  }).then(result => {
    if (result.isConfirmed) {
      const newPrice = parseFloat(result.value);
      fetch('/api/games/update_price', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: gameName, price_per_hour: newPrice })
      })
      .then(r => r.json())
      .then(resp => {
        if (resp.error) {
          Swal.fire({ icon: 'error', title: 'Error', text: resp.error });
        } else {
          Swal.fire({ icon: 'success', title: 'Updated', text: `New price: ₹${newPrice}` });
          loadGames();
        }
      })
      .catch(err => {
        console.error('Error updating price', err);
        Swal.fire({ icon: 'error', title: 'Error', text: 'Failed to update price' });
      });
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  loadGames();
  refreshAll();
  setInterval(() => {
    renderSessions();
  }, 60000);

  document.getElementById('load-user-btn').addEventListener('click', loadUser);
  document.getElementById('game-select').addEventListener('change', onGameChange);
  document.getElementById('start-session-btn').addEventListener('click', startSession);
  document.getElementById('modal-cancel-btn').addEventListener('click', closeModal);
  document.getElementById('modal-confirm-btn').addEventListener('click', confirmEndSession);
});
