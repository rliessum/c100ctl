APP_CSS = """
window.main {
  background: #121417;
}

.pad-shell {
  background: #1b1e22;
  border-radius: 28px;
  padding: 18px;
  border: 1px solid rgba(255,255,255,0.06);
}

.pad-grid {
  background: transparent;
}

.keycap {
  min-width: 64px;
  min-height: 64px;
  padding: 4px 6px;
  border-radius: 12px;
  background: #2a2e33;
  color: #d7dbe0;
  font-weight: 600;
  font-size: 11px;
  letter-spacing: 0.2px;
  border: 1px solid rgba(255,255,255,0.04);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.05);
}

.keycap:hover {
  background: #32363c;
}

.keycap.selected {
  outline: 2px solid #f0a05a;
  outline-offset: 2px;
}

.keycap.drag-preview {
  outline: 2px dashed #f0a05a;
  outline-offset: 2px;
}

.keycap.pressed {
  background: #f0a05a;
  color: #1b140e;
}

.keycap.locked {
  background: #22252a;
  color: #8b919a;
  font-weight: 500;
}

.keycap.bound-app { border-bottom: 3px solid #6ec8d4; }
.keycap.bound-command { border-bottom: 3px solid #8fd17a; }
.keycap.bound-combo { border-bottom: 3px solid #e6c35c; }
.keycap.bound-macro { border-bottom: 3px solid #e56b86; }
.keycap.bound-text { border-bottom: 3px solid #b79be8; }
.keycap.bound-profile { border-bottom: 3px solid #d48b5a; }

.key-label {
  font-size: 12px;
  font-weight: 700;
}

.key-sub {
  font-size: 9px;
  opacity: 0.7;
  font-weight: 500;
}

.status-dot {
  min-width: 8px;
  min-height: 8px;
  border-radius: 99px;
  background: #6b7178;
}
.status-dot.on { background: #8fd17a; }
.status-dot.off { background: #e56b86; }

.editor-card {
  padding: 12px;
}

.hint {
  opacity: 0.7;
  font-size: 12px;
}
"""
