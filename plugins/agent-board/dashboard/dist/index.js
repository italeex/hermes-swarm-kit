// Agent board — вкладка дашборда Hermes: карта агентов, задачи, переписка.
// Плагин Hermes Dashboard: React и компоненты берём из window.__HERMES_PLUGIN_SDK__.
(function () {
  "use strict";

  var SDK = window.__HERMES_PLUGIN_SDK__;
  var REGISTRY = window.__HERMES_PLUGINS__;
  if (!SDK || !REGISTRY) {
    console.error("Hermes Plugin SDK not found");
    return;
  }

  var React = SDK.React;
  var useState = SDK.hooks.useState;
  var useEffect = SDK.hooks.useEffect;
  var useCallback = SDK.hooks.useCallback;
  var useMemo = SDK.hooks.useMemo;
  var useRef = SDK.hooks.useRef;
  var C = SDK.components;
  var fetchJSON = SDK.fetchJSON;

  var API = "/api/plugins/agent-board";

  var STATUS_COLOR = {
    running: "#22c55e",
    ready: "#3b82f6",
    blocked: "#ef4444",
    idle: "#64748b"
  };
  var STATUS_RU = {
    running: "работает",
    ready: "ждёт запуска",
    blocked: "заблокирован",
    idle: "свободен"
  };
  var TASK_STATUS_RU = {
    running: "в работе",
    ready: "готова к проверке",
    blocked: "заблокирована",
    todo: "в очереди",
    done: "выполнена",
    scheduled: "фон"
  };

  function fmtTime(ts) {
    if (!ts) return "";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  }

  function apiGet(path) {
    return fetchJSON(API + path);
  }

  function apiPost(path, body) {
    return fetchJSON(API + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
  }

  // ------------------------------------------------------------------ canvas

  function AgentCanvas(props) {
    var agents = props.agents;
    var selected = props.selected;
    var onSelect = props.onSelect;
    var canvasRef = useRef(null);
    var boxRef = useRef(null);
    var sizeRef = useRef({ w: 800, h: 520 });
    var hoverRef = useRef(null);
    var rafRef = useRef(null);
    var bubblesRef = useRef([]);

    var layout = useCallback(function () {
      var w = sizeRef.current.w, h = sizeRef.current.h;
      var n = Math.max(agents.length, 1);
      var leader = null;
      for (var i = 0; i < agents.length; i++) if (agents[i].name === "leader") leader = agents[i];
      var rest = agents.filter(function (a) { return a !== leader; });
      var m = Math.max(rest.length, 1);
      var rx = Math.max(120, w / 2 - 230);
      var ry = Math.max(110, h / 2 - 170);
      var r = n > 6 ? 46 : n > 4 ? 52 : 58;
      var out = [];
      rest.forEach(function (a, idx) {
        var ang = (idx / m) * Math.PI * 2 - Math.PI / 2;
        out.push(Object.assign({}, a, {
          x: w / 2 + Math.cos(ang) * rx,
          y: h / 2 + Math.sin(ang) * ry,
          r: r
        }));
      });
      bubblesRef.current = leader
        ? [Object.assign({}, leader, { x: w / 2, y: h / 2, r: r + 6 })].concat(out)
        : out;
    }, [agents]);

    var draw = useCallback(function (t) {
      var cv = canvasRef.current;
      if (!cv) return;
      var dpr = window.devicePixelRatio || 1;
      var w = sizeRef.current.w, h = sizeRef.current.h;
      if (cv.width !== w * dpr || cv.height !== h * dpr) {
        cv.width = w * dpr; cv.height = h * dpr;
        cv.style.width = w + "px"; cv.style.height = h + "px";
      }
      var ctx = cv.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      var bubbles = bubblesRef.current;
      var time = (t || 0) / 1000;

      // связи: лидер в центре
      var hub = null;
      for (var q = 0; q < bubbles.length; q++) if (bubbles[q].name === "leader") hub = bubbles[q];
      if (hub) {
        ctx.strokeStyle = "rgba(140,170,220,.42)";
        ctx.lineWidth = 1.8;
        for (var i = 0; i < bubbles.length; i++) {
          var b = bubbles[i];
          if (b === hub) continue;
          var dx = b.x - hub.x, dy = b.y - hub.y, d = Math.hypot(dx, dy) || 1;
          ctx.beginPath();
          ctx.moveTo(hub.x + dx / d * (hub.r + 10), hub.y + dy / d * (hub.r + 10));
          ctx.lineTo(b.x - dx / d * (b.r + 8), b.y - dy / d * (b.r + 8));
          ctx.stroke();
        }
      }

      for (var k = 0; k < bubbles.length; k++) {
        var nb = bubbles[k];
        var col = STATUS_COLOR[nb.status] || "#64748b";
        ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r + 11, 0, 7);
        ctx.fillStyle = col + "12"; ctx.fill();

        var g = ctx.createRadialGradient(nb.x - 14, nb.y - 16, 6, nb.x, nb.y, nb.r);
        g.addColorStop(0, "#25364b"); g.addColorStop(1, "#121b2b");
        ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r, 0, 7);
        ctx.fillStyle = g; ctx.fill();
        ctx.lineWidth = 3; ctx.strokeStyle = col; ctx.stroke();

        if (nb.status === "running") {
          var dots = Math.max(1, Math.min(nb.counts.running, 6));
          for (var j = 0; j < dots; j++) {
            var ang = time * 2.2 + j * 2 * Math.PI / dots;
            ctx.beginPath();
            ctx.arc(nb.x + Math.cos(ang) * (nb.r + 13), nb.y + Math.sin(ang) * (nb.r + 13), 3.2, 0, 7);
            ctx.fillStyle = "#22c55e"; ctx.fill();
          }
          ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r + 8 + Math.sin(time * 3) * 2, 0, 7);
          ctx.strokeStyle = "rgba(34,197,94,.30)"; ctx.lineWidth = 1.5; ctx.stroke();
        } else if (nb.status === "ready") {
          ctx.save(); ctx.setLineDash([5, 7]); ctx.lineDashOffset = -time * 14;
          ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r + 10, 0, 7);
          ctx.strokeStyle = "#3b82f6"; ctx.lineWidth = 1.6; ctx.stroke(); ctx.restore();
        } else if (nb.status === "blocked") {
          var p = 0.5 + 0.5 * Math.sin(time * 4);
          ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r + 9 + p * 3, 0, 7);
          ctx.strokeStyle = "rgba(239,68,68," + (0.35 + 0.4 * p) + ")"; ctx.lineWidth = 2; ctx.stroke();
        } else {
          ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r + 8, 0, 7);
          ctx.strokeStyle = "rgba(100,116,139,.22)"; ctx.lineWidth = 1; ctx.stroke();
        }
        if (selected === nb.name) {
          ctx.beginPath(); ctx.arc(nb.x, nb.y, nb.r + 5, 0, 7);
          ctx.strokeStyle = "#e7eefb"; ctx.lineWidth = 1.6; ctx.stroke();
        }
        ctx.textAlign = "center";
        ctx.font = "600 " + (nb.r > 50 ? 15 : 13) + "px system-ui";
        ctx.fillStyle = "#eef4ff";
        var nm = nb.name.length > (nb.r > 50 ? 12 : 10) ? nb.name.slice(0, nb.r > 50 ? 12 : 10) : nb.name;
        ctx.fillText(nm, nb.x, nb.y + 1);
        ctx.font = "600 " + (nb.r > 50 ? 13 : 11.5) + "px system-ui";
        ctx.fillStyle = col;
        ctx.fillText(nb.counts.running ? nb.counts.running + " в работе"
          : (nb.status === "blocked" ? "заблокирован"
          : (nb.status === "ready" ? "ждёт запуска" : "свободен")), nb.x, nb.y + 21);
        if (nb.counts.ready && nb.counts.running) {
          ctx.font = "12px system-ui"; ctx.fillStyle = "#7d97bd";
          ctx.fillText(nb.counts.ready + " готовы", nb.x, nb.y + 37);
        }
      }
      rafRef.current = requestAnimationFrame(draw);
    }, [selected]);

    useEffect(function () {
      layout();
      rafRef.current = requestAnimationFrame(draw);
      function onResize() {
        if (!boxRef.current) return;
        var r = boxRef.current.getBoundingClientRect();
        sizeRef.current = { w: r.width, h: r.height };
        layout();
      }
      onResize();
      window.addEventListener("resize", onResize);
      return function () {
        window.removeEventListener("resize", onResize);
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
      };
    }, [layout, draw]);

    function hit(e) {
      var rect = canvasRef.current.getBoundingClientRect();
      var x = e.clientX - rect.left, y = e.clientY - rect.top;
      var bubbles = bubblesRef.current;
      for (var i = 0; i < bubbles.length; i++) {
        var b = bubbles[i];
        if (Math.hypot(b.x - x, b.y - y) <= b.r + 8) return b;
      }
      return null;
    }

    function onMove(e) {
      var b = hit(e);
      hoverRef.current = b ? b.name : null;
      canvasRef.current.style.cursor = b ? "pointer" : "default";
      props.onHover(b, e);
    }

    function onClick(e) {
      var b = hit(e);
      if (b) onSelect(b.name);
    }

    return React.createElement("div", {
      ref: boxRef,
      style: { position: "relative", width: "100%", height: "100%", minHeight: 380 }
    }, React.createElement("canvas", {
      ref: canvasRef,
      onMouseMove: onMove,
      onMouseLeave: function () { props.onHover(null, null); },
      onClick: onClick
    }));
  }

  // ------------------------------------------------------------------ панели

  function TaskLine(props) {
    var t = props.task;
    var color = {
      running: "var(--run, #22c55e)",
      ready: "var(--ready, #3b82f6)",
      blocked: "var(--blocked, #ef4444)",
      todo: "var(--todo, #94a3b8)",
      done: "var(--done, #4b5b70)"
    }[t.status] || "var(--muted, #8ba0bf)";
    return React.createElement("div", {
      style: {
        borderLeft: "2px solid " + color,
        padding: "6px 0 6px 10px",
        marginBottom: 9,
        opacity: t.status === "done" ? 0.72 : 1
      }
    },
      React.createElement("div", { style: { fontSize: 13, color: "var(--text, #e7eefb)" } }, t.title),
      React.createElement("div", { style: { fontSize: 11.5, color: "var(--muted, #8ba0bf)", marginTop: 2 } },
        (TASK_STATUS_RU[t.status] || t.status) + (props.who ? " · " + props.who : "") +
        (t.completed_at ? " · " + fmtTime(t.completed_at) : ""))
    );
  }

  function AgentPanel(props) {
    var agent = props.agent;
    if (!agent) {
      return React.createElement("div", { style: { fontSize: 13, color: "var(--muted, #8ba0bf)", padding: "20px 0", textAlign: "center" } },
        "Нажмите на пузырь агента — здесь появятся его задачи.");
    }
    var cur = agent.current.map(function (t) { return React.createElement(TaskLine, { key: t.id, task: t }); });
    var done = agent.done.map(function (t) { return React.createElement(TaskLine, { key: t.id, task: t }); });
    return React.createElement(React.Fragment, null,
      React.createElement("h3", { style: { fontSize: 14, margin: "2px 0 4px" } }, agent.name),
      React.createElement("div", { style: { fontSize: 12, color: "var(--muted, #8ba0bf)", marginBottom: 12 } },
        (STATUS_RU[agent.status] || agent.status) + " · готовы к проверке " + agent.counts.ready +
        " · выполнено " + agent.counts.done),
      cur.length ? cur : React.createElement("div", { style: { fontSize: 13, color: "var(--muted, #8ba0bf)" } }, "Сейчас задач нет"),
      React.createElement("h3", { style: { fontSize: 13, color: "var(--muted, #8ba0bf)", margin: "16px 0 8px" } },
        "Выполнено " + agent.counts.done),
      done.length ? done : React.createElement("div", { style: { fontSize: 13, color: "var(--muted, #8ba0bf)" } }, "Пока ничего не выполнено")
    );
  }

  function ChatPanel(props) {
    var feed = props.feed;
    if (!feed.length) {
      return React.createElement("div", { style: { fontSize: 13, color: "var(--muted, #8ba0bf)", padding: "20px 0", textAlign: "center" } },
        "Сообщений пока нет");
    }
    return React.createElement("div", null, feed.slice(0, 80).map(function (m, i) {
      var isOp = m.author === "оператор";
      return React.createElement("div", {
        key: (m.task_id || "x") + "-" + i,
        style: {
          borderLeft: "2px solid " + (isOp ? "var(--accent, #3b82f6)" : "var(--line, #22304a)"),
          padding: "6px 0 6px 10px",
          marginBottom: 10,
          background: isOp ? "rgba(59,130,246,.07)" : "transparent"
        }
      },
        React.createElement("b", { style: { fontSize: 12.5 } }, m.author || "—"),
        React.createElement("span", { style: { fontSize: 11.5, color: "var(--muted, #8ba0bf)", marginLeft: 6 } }, fmtTime(m.ts)),
        React.createElement("p", {
          style: { margin: "4px 0 0", fontSize: 13, color: "var(--text, #c2d0e6)", whiteSpace: "pre-wrap" }
        }, m.body)
      );
    }));
  }

  function AllTasksPanel(props) {
    var all = [];
    props.agents.forEach(function (a) {
      a.current.concat(a.done).forEach(function (t) {
        all.push(Object.assign({ who: a.name }, t));
      });
    });
    var ord = { running: 0, blocked: 1, ready: 2, todo: 3, done: 4 };
    all.sort(function (x, y) { return (ord[x.status] || 9) - (ord[y.status] || 9); });
    if (!all.length) {
      return React.createElement("div", { style: { fontSize: 13, color: "var(--muted, #8ba0bf)", padding: "20px 0", textAlign: "center" } },
        "Задач нет");
    }
    return React.createElement("div", null, all.map(function (t) {
      return React.createElement(TaskLine, { key: t.id, task: t, who: t.who });
    }));
  }

  // ------------------------------------------------------------------ страница

  function AgentBoard() {
    var sProjects = useState([]);
    var projects = sProjects[0], setProjects = sProjects[1];
    var sName = useState("");
    var name = sName[0], setName = sName[1];
    var sData = useState({ agents: [], feed: [] });
    var data = sData[0], setData = sData[1];
    var sSel = useState(null);
    var selected = sSel[0], setSelected = sSel[1];
    var sTab = useState("agent");
    var tab = sTab[0], setTab = sTab[1];
    var sText = useState("");
    var text = sText[0], setText = sText[1];
    var sStatus = useState("");
    var status = sStatus[0], setStatus = sStatus[1];
    var sTip = useState(null);
    var tip = sTip[0], setTip = sTip[1];
    var sBusy = useState(false);
    var busy = sBusy[0], setBusy = sBusy[1];

    useEffect(function () {
      apiGet("/projects").then(function (d) {
        setProjects(d.projects || []);
        if (!name && d.projects && d.projects.length) setName(d.projects[0].name);
      }).catch(function () { });
    }, []);

    useEffect(function () {
      if (!name) return;
      function load() {
        apiGet("/project/" + encodeURIComponent(name)).then(setData).catch(function () { });
      }
      load();
      var iv = setInterval(load, 2500);
      return function () { clearInterval(iv); };
    }, [name]);

    var agent = useMemo(function () {
      for (var i = 0; i < (data.agents || []).length; i++) {
        if (data.agents[i].name === selected) return data.agents[i];
      }
      return null;
    }, [data.agents, selected]);

    var counts = useMemo(function () {
      var c = { running: 0, ready: 0, blocked: 0, done: 0 };
      (data.agents || []).forEach(function (a) {
        c.running += a.counts.running; c.ready += a.counts.ready;
        c.blocked += a.counts.blocked; c.done += a.counts.done;
      });
      return c;
    }, [data.agents]);

    function onHover(b, e) {
      if (!b) { setTip(null); return; }
      setTip({ agent: b, x: e.clientX, y: e.clientY });
    }

    function send() {
      var t = text.trim();
      if (!t || busy) return;
      setBusy(true);
      setStatus("Отправляю…");
      apiPost("/say", { project: name, text: t })
        .then(function () {
          setText("");
          setStatus("Доставлено, лидер разбужен. Ответ — во вкладке «Переписка».");
          setTab("chat");
        })
        .catch(function (e) { setStatus("Ошибка: " + (e && e.detail ? e.detail : "неизвестно")); })
        .then(function () { setBusy(false); });
    }

    var tipBox = null;
    if (tip && tip.agent) {
      var ta = tip.agent;
      var cur = ta.current.slice(0, 4);
      tipBox = React.createElement("div", {
        style: {
          position: "fixed",
          left: Math.min(tip.x + 16, (typeof window !== "undefined" ? window.innerWidth : 1200) - 400),
          top: Math.max(8, tip.y - 12),
          pointerEvents: "none",
          background: "#0f1729",
          border: "1px solid var(--line, #22304a)",
          borderRadius: 10,
          padding: "9px 11px",
          fontSize: 12.5,
          maxWidth: 380,
          zIndex: 60,
          boxShadow: "0 8px 24px rgba(0,0,0,.4)"
        }
      },
        React.createElement("b", null, ta.name), " — ", STATUS_RU[ta.status] || ta.status,
        React.createElement("ul", { style: { margin: "6px 0 0", paddingLeft: 16, color: "#b9c8df" } },
          cur.length ? cur.map(function (t, i) {
            return React.createElement("li", { key: i, style: { marginBottom: 3 } }, t.title);
          }) : React.createElement("li", null, "задач в работе нет"))
      );
    }

    var projectTabs = projects.map(function (p) {
      var active = p.name === name;
      return React.createElement("button", {
        key: p.name,
        onClick: function () { setName(p.name); setSelected(null); },
        style: {
          background: active ? "rgba(59,130,246,.16)" : "transparent",
          border: "1px solid " + (active ? "var(--accent, #3b82f6)" : "var(--line, #22304a)"),
          color: active ? "var(--text, #e7eefb)" : "var(--muted, #8ba0bf)",
          borderRadius: 999,
          padding: "5px 12px",
          fontSize: 12.5,
          cursor: "pointer",
          display: "inline-flex",
          alignItems: "center",
          gap: 7
        }
      },
        React.createElement("span", {
          style: {
            width: 8, height: 8, borderRadius: "50%",
            background: p.running ? "#22c55e" : (p.blocked ? "#ef4444" : (p.ready ? "#3b82f6" : "#64748b"))
          }
        }),
        p.name,
        React.createElement("span", { style: { color: "var(--muted, #8ba0bf)" } },
          " " + p.running + "/" + p.total)
      );
    });

    return React.createElement("div", {
      style: { display: "flex", flexDirection: "column", height: "100%", minHeight: 0, gap: 12 }
    },
      // верхняя строка
      React.createElement("div", {
        style: { display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }
      },
        React.createElement("div", { style: { display: "flex", gap: 6, flexWrap: "wrap" } }, projectTabs),
        React.createElement("div", { style: { flex: 1 } }),
        React.createElement("span", { style: { fontSize: 12.5, color: "var(--muted, #8ba0bf)" } },
          counts.running + " задач в работе · " + counts.ready + " готовы · " +
          counts.blocked + " заблокировано · " + counts.done + " выполнено")
      ),

      // основная область
      React.createElement("div", {
        style: { display: "flex", gap: 12, flex: 1, minHeight: 0, alignItems: "stretch" }
      },
        // холст
        React.createElement("div", {
          style: {
            flex: 1, minWidth: 0, position: "relative",
            background: "var(--bg, #0b1020)",
            border: "1px solid var(--line, #22304a)",
            borderRadius: 14,
            overflow: "hidden"
          }
        },
          React.createElement(AgentCanvas, {
            agents: data.agents || [],
            selected: selected,
            onSelect: function (n) { setSelected(n); setTab("agent"); },
            onHover: onHover
          }),
          React.createElement("div", {
            style: {
              position: "absolute", left: 12, bottom: 10,
              display: "flex", gap: 16, alignItems: "center",
              fontSize: 12.5, color: "var(--muted, #8ba0bf)",
              background: "rgba(15,23,41,.92)",
              border: "1px solid var(--line, #22304a)",
              borderRadius: 10, padding: "8px 12px"
            }
          },
            [
              ["#22c55e", "работает"], ["#3b82f6", "ждёт запуска"],
              ["#ef4444", "заблокирован"], ["#64748b", "свободен"]
            ].map(function (pair) {
              return React.createElement("span", { key: pair[1], style: { display: "flex", alignItems: "center", whiteSpace: "nowrap" } },
                React.createElement("i", {
                  style: {
                    width: 11, height: 11, borderRadius: "50%", background: pair[0],
                    display: "inline-block", marginRight: 6
                  }
                }), pair[1]);
            }),
            React.createElement("span", { style: { color: "var(--muted, #8ba0bf)" } },
              "наведение — задачи в работе, клик — все задачи агента")
          )
        ),

        // правая колонка
        React.createElement("div", {
          style: {
            width: 380, flex: "0 0 380px", display: "flex", flexDirection: "column", gap: 10,
            minHeight: 0
          }
        },
          // поле команды
          React.createElement("div", {
            style: {
              background: "var(--panel, #121a2b)",
              border: "1px solid var(--line, #22304a)",
              borderRadius: 12, padding: 10
            }
          },
            React.createElement("textarea", {
              value: text,
              onChange: function (e) { setText(e.target.value); },
              placeholder: "Написать команде…",
              rows: 2,
              style: {
                width: "100%", boxSizing: "border-box", resize: "vertical",
                background: "var(--bg, #0b1020)", color: "var(--text, #e7eefb)",
                border: "1px solid var(--line, #22304a)", borderRadius: 8,
                padding: "8px 10px", font: "12.5px system-ui", minHeight: 44
              }
            }),
            React.createElement("div", { style: { display: "flex", gap: 8, alignItems: "center", marginTop: 7 } },
              React.createElement("button", {
                onClick: send,
                disabled: !text.trim() || busy,
                style: {
                  background: (!text.trim() || busy) ? "var(--line, #22304a)" : "var(--accent, #3b82f6)",
                  color: "#fff", border: 0, borderRadius: 8, padding: "8px 12px",
                  font: "600 12.5px system-ui", cursor: (!text.trim() || busy) ? "default" : "pointer"
                }
              }, "Отправить и разбудить лидера"),
              React.createElement("span", { style: { fontSize: 11.5, color: "var(--muted, #8ba0bf)" } }, status)
            )
          ),

          // вкладки
          React.createElement("div", { style: { display: "flex", gap: 6 } },
            [["agent", "Агент"], ["chat", "Переписка"], ["all", "Все задачи"]].map(function (pair) {
              var active = tab === pair[0];
              return React.createElement("button", {
                key: pair[0],
                onClick: function () { setTab(pair[0]); },
                style: {
                  flex: 1, background: active ? "var(--accent, #3b82f6)" : "transparent",
                  color: active ? "#fff" : "var(--muted, #8ba0bf)",
                  border: "1px solid " + (active ? "var(--accent, #3b82f6)" : "var(--line, #22304a)"),
                  borderRadius: 8, padding: "7px 0", font: "600 12px system-ui", cursor: "pointer"
                }
              }, pair[1]);
            })
          ),

          // содержимое
          React.createElement("div", {
            style: {
              flex: 1, minHeight: 0, overflowY: "auto",
              background: "var(--panel, #121a2b)",
              border: "1px solid var(--line, #22304a)",
              borderRadius: 12, padding: "12px 14px"
            }
          },
            tab === "agent" ? React.createElement(AgentPanel, { agent: agent })
              : tab === "chat" ? React.createElement(ChatPanel, { feed: data.feed || [] })
                : React.createElement(AllTasksPanel, { agents: data.agents || [] })
          )
        )
      ),
      tipBox
    );
  }

  REGISTRY.register("agent-board", AgentBoard);
})();
