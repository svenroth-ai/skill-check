import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'skill-check',
  component: 'Pane',
  requestId: 'skill-check',
  props: { title: 'Skill Check', isFocused: false, bodyColumns: 40, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} },
} as const

test('the pane is a signpost with one link, on every surface', async $ => {
  for (const surface of ['terminal', 'desktop', 'vscode', 'mobile'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    const link = await ui.find({ type: 'Link' })
    expect(link?.text).toBe('Open Companion View')
    expect(link?.props.href).toBe('http://localhost:3921')
    expect((await ui.find({ type: 'Text', text: /Skill Check/ }))?.text).toContain('Skill Check')
    await ui.unmount()
  }
})
