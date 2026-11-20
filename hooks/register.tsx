import type { Register } from 'claude-code'

const PANE = 'skill-check'
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
  const probe = `import urllib.request as u; u.urlopen("${URL}/api/skills", timeout=4)`
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

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'skill-check',
      description: 'Scan your skills and open the Skill Check view beside the chat',
    })
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
    const placed = await $.ui.open({ id: PANE, title: 'Skill Check' })
    const head = `Skill Check scanned ${summary.skills} ${summary.skills === 1 ? 'skill' : 'skills'}` +
      (summary.hard ? ` and found ${summary.hard} hard ${summary.hard === 1 ? 'finding' : 'findings'}.` : ' and found nothing that breaks a limit.')
    if (!isUp) {
      return { text: `${head}

The Companion View could not start on ${URL}. Is another program, or an older Skill Check, using port ${PORT}? Close it first, or run: python ${root}/scripts/serve.py --port <free port>` }
    }
    return { text: `${head}

**Open the Companion View:** ${URL}

Open it in your browser, or in Claude Code's built-in browser to show it in the panel on the right.` + (placed.isPlaced ? '' : ` (The panel is not drawn on this surface, use the link.)`) }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Link } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        <Text bold>Skill Check</Text>
        <Text>{summary ? `${summary.skills} ${summary.skills === 1 ? 'skill' : 'skills'} scanned. Everything stays on your computer.` : 'Run /skill-check to scan your skills.'}</Text>
        <Text> </Text>
        <Link href={URL} label="Open Companion View" />
        <Text> </Text>
        <Text dimColor>Opens the full view in your browser, or in Claude Code's built-in browser.</Text>
      </Box>
    )
  })
}
