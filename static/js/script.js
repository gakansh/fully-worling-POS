// Client‑side script for Gaming POS web app

let currentUser = null;
let gamesList = [];
let sessionsList = [];
let stationsStatus = {};
let selectedSessionId = null;

// Utility to format duration from ISO start time to now in human readable form
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

// Fetch games from server and populate select
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
        opt.textContent = game.name;
        opt.dataset.requiresControllers = game.requires_controllers;
        gameSelect.appendChild(opt);
      });
      // populate controllers select with default values 1..4
      const controllerSelect = document.getElementById('controller-select');
      controllerSelect.innerHTML = '';
      for (let i = 1; i <= 4; i++) {
        const opt = document.createElement('option');
        opt.value = i;
        opt.textContent = i;
        controllerSelect.appendChild(opt);
      }
      onGameChange();
    })
    .catch(err => console.error('Failed to load games', err));
}

// Load stations and sessions
function refreshAll() {
  fetch('/api/stations')
    .then(res => res.json())
    .then(stations => {
      stationsStatus = stations;
      populateStationSelect();
      // After station status, fetch sessions
      return fetch('/api/sessions');
    })
    .then(res => res.json())
    .then(data => {
      sessionsList = data;
      renderSessions();
    })
    .catch(err => console.error('Failed to refresh stations or sessions', err));
}

// Populate station dropdown and disable occupied ones
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

// Load or create user
function loadUser() {
  const mobile = document.getElementById('mobile-input').value.trim();
  if (!mobile) {
    alert('Please enter a mobile number');
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
      // update wallet use checkboxes default
      document.getElementById('use-wallet-checkbox').checked = true;
    })
    .catch(err => console.error('Failed to load user', err));
}

// Handle game change to show/hide controller selection
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

// Start a new session
function startSession() {
  if (!currentUser) {
    alert('Please load a user first');
    return;
  }
  const station = document.getElementById('station-select').value;
  const game = document.getElementById('game-select').value;
  const controllersVisible = !document.getElementById('controllers-row').classList.contains('hidden');
  const controllers = controllersVisible ? parseInt(document.getElementById('controller-select').value) : 0;
  const useWallet = document.getElementById('use-wallet-checkbox').checked;
  const payload = { mobile: currentUser.mobile, station, game, controllers };
  fetch('/api/start_session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(res => res.json())
    .then(resp => {
      if (resp.error) {
        alert(resp.error);
      } else {
        // Optionally clear selections or show message
        refreshAll();
      }
    })
    .catch(err => console.error('Failed to start session', err));
}

// Render active sessions table
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
    // actions cell
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

// Open modal to end session
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

// Confirm termination and generate invoice
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
        alert(resp.error);
      } else {
        closeModal();
        // update user wallet
        if (currentUser && currentUser.mobile === resp.invoice.mobile) {
          currentUser.wallet = resp.invoice.remaining_wallet;
          document.getElementById('user-wallet').textContent = currentUser.wallet.toFixed(2);
        }
        // refresh sessions and stations
        refreshAll();
        // inform the user and open invoice
        const msg = `Total Due: ₹${resp.invoice.total_due.toFixed(2)}\n` +
                    `Loyalty Earned: ₹${resp.invoice.loyalty_earned.toFixed(2)}\n` +
                    `Wallet Remaining: ₹${resp.invoice.remaining_wallet.toFixed(2)}`;
        alert(msg);
        // open PDF in new tab if available
        if (resp.pdf) {
          window.open(resp.pdf, '_blank');
        }
      }
    })
    .catch(err => {
      console.error('Failed to end session', err);
    });
}

// Event listeners
document.addEventListener('DOMContentLoaded', () => {
  loadGames();
  refreshAll();
  // refresh durations every minute
  setInterval(() => {
    renderSessions();
  }, 60000);
  document.getElementById('load-user-btn').addEventListener('click', loadUser);
  document.getElementById('game-select').addEventListener('change', onGameChange);
  document.getElementById('start-session-btn').addEventListener('click', startSession);
  document.getElementById('modal-cancel-btn').addEventListener('click', closeModal);
  document.getElementById('modal-confirm-btn').addEventListener('click', confirmEndSession);
});