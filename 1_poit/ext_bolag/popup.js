// popup.js - Enkel statusvisning

// Update status display
async function updateStatus() {
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  const statusEl = document.getElementById('status');
  const indicatorEl = document.getElementById('indicator');
  
  if (tab && tab.url && tab.url.includes('poit.bolagsverket.se')) {
    statusEl.textContent = 'Lyssnar aktivt';
    statusEl.style.color = '#4CAF50';
    indicatorEl.className = 'status-indicator active';
  } else {
    statusEl.textContent = 'Väntar på PoIT-sida';
    statusEl.style.color = '#999';
    indicatorEl.className = 'status-indicator inactive';
  }
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
  updateStatus();
  
  // Update status every 2 seconds
  setInterval(updateStatus, 2000);
});
