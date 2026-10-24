"""注入到阅读页面的样式与脚本。"""

from __future__ import annotations

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "name": "明亮",
        "bg": "#fbfaf7",
        "fg": "#23252b",
        "muted": "#6b7280",
        "accent": "#2563eb",
        "mark": "#ffe680",
        "mark_current": "#ffab2e",
        "selection": "#bcd8ff",
    },
    "sepia": {
        "name": "羊皮纸",
        "bg": "#f4ecd8",
        "fg": "#4a3f2f",
        "muted": "#8a7a63",
        "accent": "#9a6b21",
        "mark": "#f0cf7a",
        "mark_current": "#e08a2c",
        "selection": "#e6d3a8",
    },
    "dark": {
        "name": "夜间",
        "bg": "#1c1f24",
        "fg": "#c8ccd4",
        "muted": "#8b94a3",
        "accent": "#6ea8fe",
        "mark": "#6b5a1e",
        "mark_current": "#b07d1a",
        "selection": "#3a4a63",
    },
    "green": {
        "name": "护眼",
        "bg": "#c9e7c4",
        "fg": "#1f3320",
        "muted": "#4c6b4d",
        "accent": "#1f6b3a",
        "mark": "#f7e27a",
        "mark_current": "#e2b93b",
        "selection": "#a8d5a2",
    },
}


def theme_css(theme: str, font_size: int, line_height: float, max_width: int, justify: bool) -> str:
    """生成主题样式，所有关键属性都覆盖书籍自带的样式。"""

    palette = THEMES.get(theme, THEMES["light"])
    dark = theme in ("dark", "sepia", "green")
    force = f"""
      body, body *:not(a):not(mark) {{ color: {palette['fg']} !important; }}
      body a, body a * {{ color: {palette['accent']} !important; }}
      body * {{ background-color: transparent !important; }}
      body {{ background-color: {palette['bg']} !important; }}
    """ if dark else f"""
      body {{ background-color: {palette['bg']} !important; }}
    """
    align = "justify" if justify else "left"
    return f"""
    html {{
      background: {palette['bg']} !important;
      -webkit-text-size-adjust: 100%;
      font-size: {font_size}px;
    }}
    body {{
      margin: 0 auto !important;
      padding: 26px {max(18, font_size)}px 96px {max(18, font_size)}px !important;
      max-width: {max_width}px;
      font-size: {font_size}px !important;
      line-height: {line_height} !important;
      color: {palette['fg']} !important;
      background: {palette['bg']} !important;
      font-family: "Noto Serif CJK SC", "Source Han Serif SC", "Songti SC",
                   Georgia, "Microsoft YaHei", serif;
      text-align: {align};
      word-wrap: break-word;
      overflow-wrap: break-word;
      hyphens: auto;
    }}
    p, div, li, dd, dt, td, th, blockquote, pre {{
      max-width: 100%;
    }}
    p {{ margin: 0.65em 0 !important; }}
    h1, h2, h3, h4, h5, h6 {{
      line-height: 1.35 !important;
      margin: 1.1em 0 0.6em 0 !important;
      page-break-after: avoid;
    }}
    h1 {{ font-size: 1.55em; }}
    h2 {{ font-size: 1.32em; }}
    h3 {{ font-size: 1.16em; }}
    img, svg, video, canvas, table {{ max-width: 100% !important; height: auto !important; }}
    img {{ break-inside: avoid; }}
    pre, code, kbd, samp {{ font-family: "Cascadia Mono", Consolas, monospace;
      font-size: 0.92em; white-space: pre-wrap; word-break: break-word; }}
    pre {{ padding: 0.7em; border-radius: 6px; background: rgba(127,127,127,0.12) !important; }}
    blockquote {{ margin: 1em 0; padding: 0.2em 0 0.2em 1em;
      border-left: 3px solid {palette['muted']}; color: {palette['muted']} !important; }}
    hr {{ border: none; border-top: 1px solid {palette['muted']}; opacity: .5; margin: 1.6em 0; }}
    table {{ border-collapse: collapse; }}
    th, td {{ border: 1px solid {palette['muted']}; padding: 4px 8px; }}
    ::selection {{ background: {palette['selection']}; }}
    {force}
    span.er-hl {{
      background: {palette['mark']} !important;
      color: inherit !important;
      border-radius: 2px;
      padding: 0 1px;
    }}
    span.er-hl-current {{
      background: {palette['mark_current']} !important;
      box-shadow: 0 0 0 2px {palette['mark_current']};
    }}
    .er-flash {{ animation: er-flash 1.1s ease-out; }}
    @keyframes er-flash {{
      from {{ background: {palette['mark']} !important; }}
      to {{ background: transparent !important; }}
    }}
    ::-webkit-scrollbar {{ width: 11px; height: 11px; }}
    ::-webkit-scrollbar-track {{ background: transparent; }}
    ::-webkit-scrollbar-thumb {{
      background: {palette['muted']};
      border-radius: 6px;
      border: 3px solid {palette['bg']};
    }}
    ::-webkit-scrollbar-thumb:hover {{ background: {palette['accent']}; }}
    @media print {{ body {{ padding: 0; }} }}
    """


READER_JS = r"""
(function () {
  if (window.ER) { return; }
  var bridge = null;
  var markIndex = -1;
  var lastWheel = 0;
  var scrollTimer = null;

  function ratio() {
    var doc = document.documentElement;
    var max = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0) - window.innerHeight;
    if (max <= 4) { return 0; }
    return Math.min(1, Math.max(0, window.scrollY / max));
  }

  function atEnd() {
    var doc = document.documentElement;
    var max = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0) - window.innerHeight;
    return max > 4 && window.scrollY >= max - 4;
  }

  function notifyScroll() {
    if (!bridge) { return; }
    try { bridge.reportScroll(ratio(), atEnd()); } catch (err) { }
  }

  function scrollToRatio(r) {
    var doc = document.documentElement;
    var max = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0) - window.innerHeight;
    if (max <= 0) { return; }
    var value = Math.min(1, Math.max(0, r || 0));
    window.scrollTo(0, Math.round(max * value));
  }

  function goToId(id) {
    if (!id) { return false; }
    var el = document.getElementById(id);
    if (!el) {
      try { el = document.querySelector('[id="' + CSS.escape(id) + '"]'); } catch (e) { el = null; }
    }
    if (!el) {
      var named = document.getElementsByName(id);
      if (named && named.length) { el = named[0]; }
    }
    if (!el) { return false; }
    try { el.scrollIntoView({ block: 'start' }); } catch (e) { el.scrollIntoView(true); }
    el.classList.add('er-flash');
    setTimeout(function () { el.classList.remove('er-flash'); }, 1200);
    return true;
  }

  function clearMarks() {
    var nodes = document.querySelectorAll('span.er-hl');
    for (var i = 0; i < nodes.length; i++) {
      var span = nodes[i];
      var parent = span.parentNode;
      if (!parent) { continue; }
      parent.replaceChild(document.createTextNode(span.textContent), span);
      parent.normalize();
    }
    markIndex = -1;
  }

  function isSkipped(node) {
    var el = node.parentNode;
    while (el && el !== document.body) {
      var tag = el.nodeName.toLowerCase();
      if (tag === 'script' || tag === 'style' || tag === 'noscript' || tag === 'textarea') { return true; }
      if (el.classList && el.classList.contains('er-hl')) { return true; }
      el = el.parentNode;
    }
    return false;
  }

  function wrapMatches(node, pattern, limit, counter) {
    var text = node.nodeValue;
    if (!text || !/\S/.test(text)) { return; }
    var frags = [];
    var last = 0;
    var found = false;
    pattern.lastIndex = 0;
    var m;
    while ((m = pattern.exec(text)) !== null) {
      if (m[0].length === 0) { pattern.lastIndex++; continue; }
      if (m.index > last) { frags.push(document.createTextNode(text.slice(last, m.index))); }
      var span = document.createElement('span');
      span.className = 'er-hl';
      span.textContent = m[0];
      frags.push(span);
      last = m.index + m[0].length;
      found = true;
      counter.count++;
      if (limit > 0 && counter.count >= limit) { break; }
    }
    if (!found) { return; }
    if (last < text.length) { frags.push(document.createTextNode(text.slice(last))); }
    var parent = node.parentNode;
    for (var i = 0; i < frags.length; i++) { parent.insertBefore(frags[i], node); }
    parent.removeChild(node);
    parent.normalize();
  }

  function highlight(term, matchCase, wholeWord, limit) {
    clearMarks();
    if (!term) { return 0; }
    var escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    var prefix = '';
    var suffix = '';
    if (wholeWord) {
      if (/^[0-9A-Za-z_\u00c0-\uffff]/.test(term)) { prefix = '\\b'; }
      if (/[0-9A-Za-z_\u00c0-\uffff]$/.test(term)) { suffix = '\\b'; }
    }
    var pattern;
    try {
      pattern = new RegExp(prefix + escaped + suffix, matchCase ? 'g' : 'gi');
    } catch (e) {
      return 0;
    }
    var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (isSkipped(node)) { return NodeFilter.FILTER_REJECT; }
        return NodeFilter.FILTER_ACCEPT;
      }
    });
    var nodes = [];
    var current;
    while ((current = walker.nextNode()) !== null) { nodes.push(current); }
    var counter = { count: 0 };
    for (var i = 0; i < nodes.length; i++) {
      if (limit > 0 && counter.count >= limit) { break; }
      var live = nodes[i];
      if (!live.parentNode) { continue; }
      wrapMatches(live, pattern, limit, counter);
    }
    return counter.count;
  }

  function marks() {
    return Array.prototype.slice.call(document.querySelectorAll('span.er-hl'));
  }

  function focusMark(direction) {
    var list = marks();
    if (!list.length) { return -1; }
    if (markIndex < 0) { markIndex = direction >= 0 ? 0 : list.length - 1; }
    else { markIndex = (markIndex + direction + list.length) % list.length; }
    for (var i = 0; i < list.length; i++) { list[i].classList.remove('er-hl-current'); }
    var el = list[markIndex];
    el.classList.add('er-hl-current');
    try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); }
    catch (e) { el.scrollIntoView(); }
    return markIndex;
  }

  function focusMarkAt(index) {
    var list = marks();
    if (!list.length) { return -1; }
    index = Math.floor(index);
    if (index < 0) { index = 0; }
    if (index >= list.length) { index = list.length - 1; }
    markIndex = index;
    for (var i = 0; i < list.length; i++) { list[i].classList.remove('er-hl-current'); }
    var el = list[markIndex];
    el.classList.add('er-hl-current');
    try { el.scrollIntoView({ block: 'center', behavior: 'auto' }); }
    catch (e) { el.scrollIntoView(); }
    return markIndex;
  }

  function page(dir) {
    var before = window.scrollY;
    window.scrollBy(0, dir * Math.max(240, Math.round(window.innerHeight * 0.9)));
    var moved = Math.abs(window.scrollY - before) > 2;
    if (bridge) { try { bridge.reportPageTurn(dir > 0, moved); } catch (e) { } }
    return moved;
  }

  function scrollToOffsetInBlock(blockId, fraction) {
    var el = blockId ? document.getElementById(blockId) : null;
    if (!el) { return false; }
    try { el.scrollIntoView({ block: 'start' }); } catch (e) { el.scrollIntoView(true); }
    var rect = el.getBoundingClientRect();
    if (fraction > 0) { window.scrollBy(0, Math.round(rect.height * Math.min(1, fraction))); }
    return true;
  }

  window.ER = {
    attach: function (obj) {
      bridge = obj;
      try { bridge.pageReady(); } catch (e) { }
    },
    ratio: ratio,
    scrollToRatio: scrollToRatio,
    goToId: goToId,
    scrollToBlock: scrollToOffsetInBlock,
    highlight: highlight,
    clearMarks: clearMarks,
    focusMark: focusMark,
    focusMarkAt: focusMarkAt,
    markCount: function () { return marks().length; },
    page: page,
    notify: notifyScroll
  };

  window.addEventListener('scroll', function () {
    if (scrollTimer) { return; }
    scrollTimer = setTimeout(function () { scrollTimer = null; notifyScroll(); }, 180);
  }, { passive: true });

  window.addEventListener('wheel', function (event) {
    if (!bridge) { return; }
    var now = Date.now();
    if (now - lastWheel < 550) { return; }
    var doc = document.documentElement;
    var max = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0) - window.innerHeight;
    if (max <= 4) { lastWheel = now; try { bridge.reportPageTurn(event.deltaY > 0, false); } catch (e) { } return; }
    var down = event.deltaY > 0;
    if (down && window.scrollY >= max - 6) {
      lastWheel = now;
      try { bridge.reportPageTurn(true, false); } catch (e) { }
    } else if (!down && window.scrollY <= 4) {
      lastWheel = now;
      try { bridge.reportPageTurn(false, false); } catch (e) { }
    }
  }, { passive: true });

  document.addEventListener('click', function (event) {
    var target = event.target;
    var anchor = target && target.closest ? target.closest('a') : null;
    if (!anchor) { return; }
    var href = anchor.getAttribute('href') || '';
    if (!href) { return; }
    var lowered = href.toLowerCase();
    if (lowered.indexOf('javascript:') === 0) { event.preventDefault(); return; }
    event.preventDefault();
    if (href.charAt(0) === '#') {
      var frag = href.slice(1);
      try { frag = decodeURIComponent(frag); } catch (e) { }
      if (goToId(frag)) { return; }
    }
    if (bridge) { try { bridge.linkClicked(href); } catch (e) { } }
  }, false);

  function boot(channel) {
    var attempts = 0;
    var timer = setInterval(function () {
      if (!channel || !channel.objects || !channel.objects.bridge) {
        attempts++;
        if (attempts > 100) { clearInterval(timer); }
        return;
      }
      clearInterval(timer);
      window.ER.attach(channel.objects.bridge);
    }, 30);
  }

  function connect() {
    if (typeof QWebChannel === 'undefined') { return; }
    new QWebChannel(qt.webChannelTransport, boot);
  }

  if (typeof QWebChannel !== 'undefined') {
    connect();
  } else {
    var script = document.createElement('script');
    script.src = 'qrc:///qtwebchannel/qwebchannel.js';
    script.onload = connect;
    (document.head || document.documentElement).appendChild(script);
  }
})();
"""
