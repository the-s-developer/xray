from nicegui import ui

left_open = True
right_open = True
bottom_open = True

def toggle_left():
    global left_open
    left_open = not left_open
    left_panel.visible = left_open
    left_open_btn.visible = not left_open

def toggle_right():
    global right_open
    right_open = not right_open
    right_panel.visible = right_open
    right_open_btn.visible = not right_open

def toggle_bottom():
    global bottom_open
    bottom_open = not bottom_open
    bottom_panel.visible = bottom_open
    bottom_open_btn.visible = not bottom_open

ui.dark_mode()

with ui.row().style('height: 100vh; overflow: hidden;'):
    # SOL PANEL
    with ui.column().style('width: 220px; background: #222831; color: #fff; border-right:1px solid #393e46;').bind_visibility(lambda: left_open) as left_panel:
        with ui.row().style('justify-content: flex-end;'):
            ui.button(icon='close', on_click=toggle_left, color='grey').props('flat round dense').style('margin:2px 0 2px 0; padding:0; min-width:22px;')
        ui.label('EXPLORER').style('font-weight:bold; margin-top:8px;')
        ui.separator()
        ui.label('.profile')
        ui.label('.bashrc')
        ui.label('.bash_logout')
        ui.separator()
        ui.label('Tool Settings').style('font-weight:bold; margin-top:8px;')
        ui.input('System Prompt', value='You are a helpful assistant.')
        ui.select(['gpt-4.1-nano', 'gpt-4o', 'gpt-4-turbo', 'gpt-4', 'gpt-3.5-turbo'], value='gpt-4.1-nano', label='Model')
    left_open_btn = ui.button(icon='chevron_right', on_click=toggle_left, color='grey').props('flat round dense').style('margin-left:4px; min-width:22px;').bind_visibility(lambda: not left_open)

    # ANA PANEL
    with ui.column().style('flex: 1; min-width:0; background:#1e1e1e; color:#eee; position:relative;'):
        with ui.row().style('padding:0 0 4px 0; border-bottom:1px solid #393e46;'):
            ui.label('Chat').style('font-size:1.1em; margin: 8px 12px;')
            ui.label('Python Canvas').style('font-size:1.1em; margin: 8px 12px; color:#999;')
        ui.textarea(label='Chat', placeholder='Type your message...', rows=3)
        ui.button('Send')
        ui.button('Clear Chat')
        right_open_btn = ui.button(icon='chevron_left', on_click=toggle_right, color='grey').props('flat round dense').style('position:absolute; top:4px; right:0; min-width:22px; z-index:10;').bind_visibility(lambda: not right_open)
        bottom_open_btn = ui.button(icon='expand_less', on_click=toggle_bottom, color='grey').props('flat round dense').style('position:absolute; left:50%; bottom:4px; min-width:22px; transform:translateX(-50%); z-index:10;').bind_visibility(lambda: not bottom_open)

    # SAĞ PANEL
    with ui.column().style('width: 260px; background: #222831; color: #fff; border-left:1px solid #393e46;').bind_visibility(lambda: right_open) as right_panel:
        with ui.row().style('justify-content: flex-end;'):
            ui.button(icon='close', on_click=toggle_right, color='grey').props('flat round dense').style('margin:2px 0 2px 0; padding:0; min-width:22px;')
        ui.label('Sağ Panel').style('font-weight:bold; margin-top:8px;')
        ui.json({'info': 'Buraya inspector veya başka içerik ekleyebilirsin.'})

# ALT PANEL (Terminal)
with ui.row().style('position:fixed; left:0; right:0; bottom:0; background:#23272f; color:#eee; border-top:1px solid #393e46; z-index:20; height:140px;').bind_visibility(lambda: bottom_open) as bottom_panel:
    with ui.column().style('width:100%;'):
        with ui.row().style('justify-content:flex-end;'):
            ui.button(icon='close', on_click=toggle_bottom, color='grey').props('flat round dense').style('margin:2px 0 2px 0; padding:0; min-width:22px;')
        ui.label('TERMINAL • OUTPUT • DEBUG CONSOLE • PORTS').style('font-size:0.95em; margin-left:8px;')
        ui.markdown('```bash\ncoder@xxxx:~$ \n```')

ui.run()
