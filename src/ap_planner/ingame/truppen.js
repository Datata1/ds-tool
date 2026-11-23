// ap-planner - Truppen des Stammes auslesen (Schnellleisten-Skript)
// Version: 1.0.0 · Lizenz: MIT · https://github.com/ (ap-planner)
//
// Was es tut:
// - Laeuft nur auf "Stamm -> Mitglieder -> Truppen" (sonst wechselt es dorthin).
// - Liest nacheinander die Truppen-Seite jedes Mitglieds, das seine Truppen mit dem Stamm teilt.
//   Nur Lesen (GET), eine Seite nach der anderen, mit Pause dazwischen. Keine Spielaktionen.
// - Zeigt das Ergebnis als Text zum Kopieren. Es wird NICHTS an fremde Server geschickt und kein
//   Code nachgeladen. Den Text in den ap-planner einfuegen (oder einfach kopieren, wenn der
//   Sammel-Modus laeuft).
//
// Keine Gewaehr: Ob Skripte auf deiner Welt erlaubt sind, regeln die Spielregeln von InnoGames.
//
// Regeln fuer diese Datei (wird zu einer Zeile fuer die Schnellleiste zusammengefuegt):
// Kommentare nur in eigenen Zeilen, jede Anweisung endet mit ";".
(function () {
  "use strict";
  var VERSION = "1.0.0";
  var PAUSE_MS = 600;
  var MAX_PLAYERS = 300;
  var UNITS = ["spear", "sword", "axe", "archer", "spy", "light", "marcher", "heavy", "ram", "catapult", "knight", "snob", "militia"];
  var BOX_ID = "ap-troops-box";
  var params = new URLSearchParams(location.search);
  if (params.get("screen") !== "ally" || params.get("mode") !== "members_troops") {
    if (window.confirm("ap-planner: Das Skript laeuft auf Stamm -> Mitglieder -> Truppen. Jetzt dorthin wechseln? Danach das Skript nochmal anklicken.")) {
      var target = new URL(location.href);
      target.search = "";
      target.searchParams.set("screen", "ally");
      target.searchParams.set("mode", "members_troops");
      if (params.get("village")) {
        target.searchParams.set("village", params.get("village"));
      }
      if (params.get("t")) {
        target.searchParams.set("t", params.get("t"));
      }
      location.href = target.toString();
    }
    return;
  }
  if (document.getElementById(BOX_ID)) {
    document.getElementById(BOX_ID).remove();
  }
  var stopped = false;
  var box = document.createElement("div");
  box.id = BOX_ID;
  box.style.cssText = "position:fixed;top:60px;right:20px;z-index:99999;width:420px;max-width:90vw;background:#f4e4bc;border:2px solid #7d510f;padding:10px;font:13px Verdana,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.4)";
  var title = document.createElement("b");
  title.textContent = "ap-planner: Truppen auslesen (v" + VERSION + ")";
  var status = document.createElement("div");
  status.style.margin = "8px 0";
  var out = document.createElement("textarea");
  out.readOnly = true;
  out.style.cssText = "width:100%;height:120px;display:none;font:11px monospace";
  var buttons = document.createElement("div");
  var stopBtn = document.createElement("button");
  stopBtn.className = "btn";
  stopBtn.textContent = "Abbrechen";
  var copyBtn = document.createElement("button");
  copyBtn.className = "btn";
  copyBtn.textContent = "Kopieren";
  copyBtn.style.display = "none";
  var closeBtn = document.createElement("button");
  closeBtn.className = "btn";
  closeBtn.textContent = "Schliessen";
  buttons.appendChild(stopBtn);
  buttons.appendChild(copyBtn);
  buttons.appendChild(closeBtn);
  box.appendChild(title);
  box.appendChild(status);
  box.appendChild(out);
  box.appendChild(buttons);
  document.body.appendChild(box);
  stopBtn.onclick = function () {
    stopped = true;
    status.textContent = "Abgebrochen.";
  };
  closeBtn.onclick = function () {
    stopped = true;
    box.remove();
  };
  copyBtn.onclick = function () {
    out.select();
    var done = function () {
      copyBtn.textContent = "Kopiert!";
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(out.value).then(done, function () {
        document.execCommand("copy");
        done();
      });
    } else {
      document.execCommand("copy");
      done();
    }
  };
  function unitOf(cell) {
    var img = cell.querySelector("img");
    var hay = (img ? (img.getAttribute("src") || "") + " " + (img.className || "") : "") + " " + (cell.getAttribute("data-unit") || "") + " " + (cell.className || "");
    for (var i = 0; i < UNITS.length; i++) {
      if (new RegExp("unit_" + UNITS[i] + "\\b").test(hay) || new RegExp("\\b" + UNITS[i] + "\\.(png|webp|gif)").test(hay)) {
        return UNITS[i];
      }
    }
    return null;
  }
  function grid(table) {
    var rows = [];
    var trs = table.querySelectorAll("tr");
    for (var r = 0; r < trs.length; r++) {
      rows[r] = rows[r] || [];
      var c = 0;
      var cells = trs[r].children;
      for (var k = 0; k < cells.length; k++) {
        while (rows[r][c]) {
          c++;
        }
        var rs = parseInt(cells[k].getAttribute("rowspan") || "1", 10);
        var cs = parseInt(cells[k].getAttribute("colspan") || "1", 10);
        for (var dr = 0; dr < rs; dr++) {
          rows[r + dr] = rows[r + dr] || [];
          for (var dc = 0; dc < cs; dc++) {
            rows[r + dr][c + dc] = cells[k];
          }
        }
        c += cs;
      }
    }
    return rows;
  }
  function toInt(text) {
    var n = parseInt(String(text).replace(/[^\d]/g, ""), 10);
    return isNaN(n) ? 0 : n;
  }
  function parsePage(html, player) {
    var doc = new DOMParser().parseFromString(html, "text/html");
    var tables = doc.querySelectorAll("table");
    var found = [];
    for (var t = 0; t < tables.length; t++) {
      var g = grid(tables[t]);
      var cols = {};
      var headerRows = Math.min(4, g.length);
      for (var h = 0; h < headerRows; h++) {
        for (var ci = 0; ci < (g[h] || []).length; ci++) {
          var u = g[h][ci] ? unitOf(g[h][ci]) : null;
          if (u && cols[ci] === undefined) {
            cols[ci] = u;
          }
        }
      }
      if (Object.keys(cols).length < 3) {
        continue;
      }
      for (var r = 0; r < g.length; r++) {
        var row = g[r] || [];
        var text = "";
        var seen = [];
        for (var x = 0; x < row.length; x++) {
          if (row[x] && seen.indexOf(row[x]) < 0) {
            seen.push(row[x]);
            text += " " + row[x].textContent;
          }
        }
        var m = /(.*?)\(?\b(\d{1,3})\|(\d{1,3})\b/.exec(text);
        if (!m) {
          continue;
        }
        var units = {};
        var any = false;
        for (var key in cols) {
          if (row[key] && /\d/.test(row[key].textContent)) {
            units[cols[key]] = toInt(row[key].textContent);
            any = true;
          }
        }
        if (!any) {
          continue;
        }
        found.push({ x: parseInt(m[2], 10), y: parseInt(m[3], 10), name: m[1].replace(/\s+/g, " ").replace(/[(\s]+$/, "").trim(), player: player, units: units });
      }
      if (found.length) {
        break;
      }
    }
    return found;
  }
  function members() {
    var ids = {};
    var list = [];
    var add = function (id, name) {
      if (id && !ids[id]) {
        ids[id] = true;
        list.push({ id: id, name: (name || "").trim() || ("Spieler " + id) });
      }
    };
    var options = document.querySelectorAll("select option");
    for (var i = 0; i < options.length; i++) {
      var sel = options[i].parentElement;
      if (sel && /player/.test(sel.name || sel.id || "") && /^\d+$/.test(options[i].value)) {
        add(options[i].value, options[i].textContent);
      }
    }
    var links = document.querySelectorAll("#content_value a[href*='player_id='], #content_value a[href*='screen=info_player']");
    for (var j = 0; j < links.length; j++) {
      var mm = /[?&](?:player_id|id)=(\d+)/.exec(links[j].getAttribute("href") || "");
      if (mm) {
        add(mm[1], links[j].textContent);
      }
    }
    return list.slice(0, MAX_PLAYERS);
  }
  function pageUrl(id) {
    var u = new URL(location.href);
    u.searchParams.set("screen", "ally");
    u.searchParams.set("mode", "members_troops");
    u.searchParams.set("player_id", id);
    u.searchParams.delete("page");
    return u.toString();
  }
  var players = members();
  if (!players.length) {
    status.textContent = "Keine Mitglieder gefunden. Teilen die Mitglieder ihre Truppen mit dem Stamm, und siehst du die Truppen-Seite?";
    stopBtn.style.display = "none";
    return;
  }
  var villages = [];
  var empty = [];
  var failed = [];
  var index = 0;
  function finish() {
    stopBtn.style.display = "none";
    var world = (window.game_data && window.game_data.world) || location.hostname.split(".")[0];
    var result = { format: "ap-troops/1", version: VERSION, world: world, created: new Date().toISOString(), villages: villages };
    out.value = JSON.stringify(result);
    out.style.display = "block";
    copyBtn.style.display = "inline-block";
    var note = villages.length + " Doerfer von " + (players.length - empty.length - failed.length) + " Spielern gelesen" + (stopped ? " (abgebrochen)" : "") + ".";
    if (empty.length) {
      note += " Ohne Truppen-Daten: " + empty.join(", ") + ".";
    }
    if (failed.length) {
      note += " Fehler bei: " + failed.join(", ") + ".";
    }
    status.textContent = note + " Jetzt \"Kopieren\" und in den ap-planner einfuegen.";
  }
  function next() {
    if (stopped || index >= players.length) {
      finish();
      return;
    }
    var p = players[index];
    index++;
    status.textContent = "Lese " + index + "/" + players.length + ": " + p.name + " ...";
    fetch(pageUrl(p.id), { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) {
        throw new Error("HTTP " + r.status);
      }
      return r.text();
    }).then(function (html) {
      var rows = parsePage(html, p.name);
      if (rows.length) {
        villages = villages.concat(rows);
      } else {
        empty.push(p.name);
      }
    }).catch(function () {
      failed.push(p.name);
    }).then(function () {
      setTimeout(next, PAUSE_MS);
    });
  }
  next();
})();
