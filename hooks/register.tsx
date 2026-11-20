import type { Register } from 'claude-code'

const PORT = '3921' // not 3920: that port is used by other local tools in the author's setups
const URL = `http://localhost:${PORT}`
const MIN_PYTHON = '3.10' // the scripts use syntax from 3.10; the README says the same

type Summary = { skills: number; findings: number; hard: number; top: { skill: string; tokens: number }[] }

// The page itself is served by scripts/serve.py and opened in a browser: a pane can only draw native elements
// (text, buttons, links), it cannot embed a web page. So the pane is a signpost with one link.

// A hot reload loses module variables. The pane then shows the prompt to run the command again, which is
// the right fallback: nothing here is state worth keeping.
let summary: Summary | undefined
let isServing = false
let isListening = false
let python: string[] | undefined

function parseSummary(out: string): Summary | undefined {
  try {
    const line = out.trim().split('\n').filter(Boolean).pop() ?? ''
    const v = JSON.parse(line)
    if (typeof v?.skills !== 'number' || !Array.isArray(v?.top)) return undefined
    return v as Summary
  } catch {
    return undefined
  }
}

// Windows and many Linux setups name it python, macOS usually python3. Accept only 3.10 or newer.
async function findPython($: any): Promise<string[] | undefined> {
  if (python) return python
  // python, python3, or uv (which brings its own Python 3.10 or newer when none is installed)
  for (const cmd of [['python'], ['python3'], ['uv', 'run', '--no-project', '--python', '3.10', 'python']]) {
    try {
      const r = await $.process.run([...cmd, '-c', 'import sys; print(int(sys.version_info >= (3, 10)))'])
      if (r.exitCode === 0 && r.stdout.trim() === '1') return (python = cmd)
    } catch {
      // not on the path, try the next name
    }
  }
  return undefined
}

// The server exits with code 2 when the port is taken, so ask it: up means the scan route answers.
async function waitForServer($: any, py: string[]): Promise<boolean> {
  const probe = `import urllib.request as u; u.urlopen("${URL}/api/intent/status", timeout=4)`
  for (let i = 0; i < 20; i++) {
    try {
      const r = await $.process.run([...py, '-c', probe], { timeoutMs: 5000 })
      if (r.exitCode === 0) return true
    } catch {
      // not up yet
    }
    await $.clock.sleep(250)
  }
  return false
}

function listen($: any): void {
  if (isListening) return
  {
    isListening = true
    // A click in the view (for example "Start the upgrade") is picked up here and goes on in the chat, as the
    // person's own words. The view only ever queues fixed sentences for a skill that exists and is the person's.
    let isBusy = false
    $.ui.log('skill-check chat link: started', { to: 'debug' })
    $.clock.every(2000, async () => {
      if (isBusy) return
      isBusy = true
      try {
        const r = await $.http.fetch(`${URL}/api/intent/take`, { method: 'POST', headers: { Origin: URL, 'Content-Type': 'application/json' }, body: '{}' })
        const text = r.ok ? JSON.parse(r.text || '{}').text : undefined
        if (typeof text === 'string' && text) await $.prompt.submit({ text, asUser: true })
      } catch (err) {
        $.ui.log(`skill-check chat link: ${String(err)}`, { to: 'debug' })
      } finally {
        isBusy = false
      }
    })
  }
}

// Start the view in the background (once) and the link from the view to the chat. Called when the session starts,
// so the view is already there when someone needs it, and again by /skill-check.
async function ensureView($: any, py: string[]): Promise<boolean> {
  const root = $.plugin.root
  if (!isServing) {
    isServing = true
    void (async () => {
      try {
        const server = $.process.spawn({ argv: [...py, `${root}/scripts/serve.py`, '--port', PORT] })
        for await (const { text } of server) $.ui.log(text, { to: 'debug' })
      } catch (err) {
        $.ui.log(`skill-check server did not start: ${String(err)}`, { to: 'debug' })
      } finally {
        isServing = false
      }
    })()
  }
  const isUp = await waitForServer($, py)
  if (isUp) listen($)
  return isUp
}

let isWarmed = false

export const register: Register = on => {
  // The first turn of a session also starts the view, in case session.start could not.
  on('turn.start', async ($, e, next) => {
    if (!isWarmed) {
      isWarmed = true
      try {
        const py = await findPython($)
        if (py) await ensureView($, py)
      } catch (err) {
        $.ui.log(`skill-check: view not started: ${String(err)}`, { to: 'debug' })
      }
    }
    return next(e)
  })

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'skill-check',
      description: 'Scan your skills and open the Skill Check view beside the chat',
    })
    listen($) // needs no process: it only asks the view for clicks, and stays quiet while the view is down
    // Quietly start the view so it is ready for Skill Upgrade too. It listens on this computer only.
    try {
      const py = await findPython($)
      if (py) $.ui.log(`skill-check: view ${(await ensureView($, py)) ? 'up' : 'not up'}`, { to: 'debug' })
    } catch (err) {
      $.ui.log(`skill-check: view not started: ${String(err)}`, { to: 'debug' })
    }
    return next(e)
  })

  on('command.run', { command: 'skill-check' }, async $ => {
    const py = await findPython($)
    if (!py) return { text: `Skill Check needs Python ${MIN_PYTHON} or newer on the path. Install it, then run /skill-check again.` }
    const root = $.plugin.root
    const scan = await $.process.run([...py, `${root}/scripts/check_skills.py`, '--summary'], { timeoutMs: 120000 })
    if (scan.exitCode !== 0) return { text: `The scan failed: ${scan.stderr.trim() || 'no message'}` }
    const parsed = parseSummary(scan.stdout)
    if (!parsed) return { text: 'The scan finished but returned no readable summary. Run: python scripts/check_skills.py' }
    summary = parsed

    const isUp = await ensureView($, py)
    const head = `Skill Check scanned ${summary.skills} ${summary.skills === 1 ? 'skill' : 'skills'}` +
      (summary.hard ? ` and found ${summary.hard} hard ${summary.hard === 1 ? 'finding' : 'findings'}.` : ' and found nothing that breaks a limit.')
    if (!isUp) {
      return { text: `${head}

The Companion View could not start on ${URL}. Is another program, or an older Skill Check, using port ${PORT}? Close it first, or run: python ${root}/scripts/serve.py --port <free port>` }
    }
    return { text: `${head}

**Open the Companion View:** ${URL}

**Next step:** choose a skill in the Companion View. When you click there, I carry on in this chat, so you always see what is happening on the left and use the view as your helper on the right. In the desktop app the link opens beside the chat or in your browser, as you set it under links. In a terminal, open it in your browser.` }
  })
}
