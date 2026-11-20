import type { Register } from 'claude-code'

const PANE = 'skill-check'
const PORT = '3921' // not 3920: that port is used by other local tools in the author's setups
const URL = `http://localhost:${PORT}`
const MIN_PYTHON = '3.10' // the scripts use syntax from 3.10; the README says the same

type Summary = { skills: number; findings: number; hard: number; top: { skill: string; tokens: number }[] }

type Model = {
  steps: { id: string; label: string; state: 'done' | 'current' | 'later' }[]
  skills: { name: string; verdict: string; headline: string }[]
  selected: null | { name: string; verdict: string; sentences: string[] }
  next: { label: string; why: string; prompt: string | null; available: boolean }
}

// What the pane shows comes from scripts/view_model.py (plain words, tested in Python). This file only draws
// it and starts the next step: it holds no wording of its own.
let model: Model | undefined
let selected: string | undefined
let env: { py: string[]; root: string } | undefined
let note: string | undefined

let seq = 0 // the newest request wins: a slow answer for an earlier press must not overwrite a later one
let sent = false // one press sends one prompt, until the next draw

const FAILED = 'The view could not be updated. Run /skill-check again.'

async function loadModel($: any, want: string | undefined): Promise<void> {
  if (!env) return
  const mine = ++seq
  const args = [...env.py, `${env.root}/scripts/view_model.py`, ...(want ? ['--skill', want] : [])]
  try {
    const r = await $.process.run(args, { timeoutMs: 20000 })
    if (mine !== seq) return
    if (r.exitCode === 0) {
      model = JSON.parse(r.stdout) as Model
      selected = want // only a successful load moves the choice
      note = undefined
    } else {
      note = FAILED // never the raw error: it holds paths and tracebacks
      $.ui.log(`skill-check view: ${r.stderr.trim()}`, { to: 'debug' })
    }
  } catch (err) {
    if (mine !== seq) return
    note = FAILED
    $.ui.log(`skill-check view: ${String(err)}`, { to: 'debug' })
  }
  sent = false
  $.ui.invalidate('ui.render')
}

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
    env = { py, root }
    await loadModel($, undefined)

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
    const head = `Scanned ${summary.skills} skills: ${summary.hard} hard findings.`
    if (!isUp) {
      return { text: `${head} The view could not start on ${URL} (is another program, or an older Skill Check, using port ${PORT}? Close it first). Run: python ${root}/scripts/serve.py --port <free port>` }
    }
    return { text: `${head} Full view: ${URL}` + (placed.isPlaced ? '' : ' (the panel is not drawn on this surface, use the link)') }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Link, Button } = $.ui.resolve(e)
    if (!model) return <Text dimColor>{note ?? 'Run /skill-check to scan.'}</Text>
    const m = model
    const mark = { done: '✓', current: '●', later: '○' }
    const choose = (name: string | undefined) => {
      void loadModel($, name)
    }
    const go = () => {
      if (!m.next.prompt || sent) return
      sent = true // a second press before the next draw does nothing
      void $.prompt.submit({ text: m.next.prompt })
    }
    return (
      <Box flexDirection="column">
        {m.steps.map(s => (
          <Text bold={s.state === 'current'} dimColor={s.state === 'later'}>
            {mark[s.state]} {s.label}
          </Text>
        ))}
        <Text> </Text>
        {m.selected ? (
          <Box flexDirection="column">
            <Text bold>{m.selected.name}</Text>
            <Text dimColor>{m.selected.verdict}</Text>
            {m.selected.sentences.map(line => (
              <Text>{line}</Text>
            ))}
            <Button key="back" onPress={() => choose(undefined)}>Back to all skills</Button>
          </Box>
        ) : (
          <Box flexDirection="column">
            <Text bold>Your skills</Text>
            {m.skills.slice(0, 8).map(s => (
              <Button key={s.name} onPress={() => choose(s.name)}>{s.name} <Text dimColor>{s.headline}</Text></Button>
            ))}
            {m.skills.length > 8 && <Text dimColor>and {m.skills.length - 8} more, in the full view</Text>}
          </Box>
        )}
        <Text> </Text>
        <Text>{m.next.why}</Text>
        {m.next.prompt ? (
          <Button key="next" variant="primary" onPress={go}>{m.next.label}</Button>
        ) : (
          <Text bold>{m.next.label}</Text>
        )}
        {note && <Text color="yellow">{note}</Text>}
        <Text> </Text>
        <Link href={URL} label="Open the full view" />
      </Box>
    )
  })
}
