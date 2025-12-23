"""
Version: v1
Design, Author, Updated by: Girish Subramanya <girish.subramanya@daimlertruck.com>, VCP, B&I, DTICI
Date: 2025-12-23
"""
from flask import Flask, render_template, request, jsonify
import yaml
import json
import os
import re

# Configure PyYAML to use block style for multiline strings
# AND preserve user-supplied quotes if present.
def str_presenter(dumper, data):
    style = None

    # Check if the string is explicitly quoted by the user
    # We check for matching start/end quotes and length >= 2
    if len(data) >= 2:
        if data.startswith('"') and data.endswith('"'):
            style = '"'
            data = data[1:-1]
        elif data.startswith("'") and data.endswith("'"):
            style = "'"
            data = data[1:-1]

    # Apply user-requested specific quoting rules for unquoted inputs
    if style is None:
        if data == '.' or '\\' in data:
            style = '"'

    if len(data.splitlines()) > 1:  # check for multiline string
        # Ensure it ends with a newline to force '|' instead of '|-'
        if not data.endswith('\n'):
            data += '\n'
        return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')

    return dumper.represent_scalar('tag:yaml.org,2002:str', data, style=style)

yaml.add_representer(str, str_presenter)

app = Flask(__name__)

class NoBoolSafeLoader(yaml.SafeLoader):
    pass

def construct_yaml_bool(self, node):
    return self.construct_scalar(node)

NoBoolSafeLoader.add_constructor(u'tag:yaml.org,2002:bool', construct_yaml_bool)

@app.route('/')
def index():
    steps_config = []
    workflows_config = []
    trigger_config = {}
    try:
        # Assuming steps_config.json is in the same directory as app.py
        config_path = os.path.join(os.path.dirname(__file__), 'steps_config.json')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                steps_config = json.load(f)

        # Load trigger config
        trigger_config_path = os.path.join(os.path.dirname(__file__), 'trigger_config.json')
        if os.path.exists(trigger_config_path):
            with open(trigger_config_path, 'r') as f:
                trigger_config = json.load(f)

        # Load workflows config from predefined_workflows directory
        wf_dir = os.path.join(os.path.dirname(__file__), 'predefined_workflows')
        if os.path.exists(wf_dir):
            for filename in os.listdir(wf_dir):
                if filename.endswith('.yml') or filename.endswith('.yaml'):
                    filepath = os.path.join(wf_dir, filename)
                    try:
                        with open(filepath, 'r') as f:
                            # Use NoBoolSafeLoader to ensure 'on' is read as string
                            data = yaml.load(f, Loader=NoBoolSafeLoader)
                            if data:
                                workflows_config.append({
                                    "label": data.get('name', filename),
                                    "description": "", # YAML doesn't have standard desc field
                                    "data": data
                                })
                    except Exception as e:
                        print(f"Error reading {filename}: {e}")

        # Sort by label
        workflows_config.sort(key=lambda x: x['label'])

    except Exception as e:
        print(f"Error loading config: {e}")

    return render_template('index.html', steps_config=steps_config, workflows_config=workflows_config, trigger_config=trigger_config)

@app.route('/parse_yaml', methods=['POST'])
def parse_yaml():
    try:
        yaml_content = request.get_data(as_text=True)
        # Use BaseLoader or custom loader to avoid boolean conversion of keys
        # But 'on' is interpreted as boolean True in YAML 1.1, which PyYAML implements by default?
        # Actually PyYAML follows YAML 1.1 where on/off/yes/no are booleans.
        # GitHub Actions uses YAML 1.2 mostly, where on is string.
        # We need to tell PyYAML to treat 'on' as string.

        # We can use SafeLoader but override bool resolver?
        # Or just use yaml.load with a custom loader.

        # Simple hack: replace "on:" with "'on':" if it is a key?
        # But that's risky with regex.

        # Better: use a loader that doesn't resolve on/off/yes/no as bools.

        data = yaml.load(yaml_content, Loader=NoBoolSafeLoader)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

# @app.route('/save_template', methods=['POST'])
# Route removed in favor of client-side download

@app.route('/generate', methods=['POST'])
def generate_yaml():
    data = request.json
    # data is expected to be the workflow structure

    workflow = {
        'name': data.get('name', 'CI'),
        'on': data.get('on', {}),
        'jobs': data.get('jobs', {})
    }

    # Handle global environment variables and map workflow_dispatch inputs
    # env removed as per request

    yaml_output = yaml.dump(workflow, sort_keys=False, default_flow_style=False)

    # Check if 'on' is quoted.
    yaml_output = re.sub(r"^'on':", "on:", yaml_output, flags=re.MULTILINE)
    yaml_output = re.sub(r'^"on":', "on:", yaml_output, flags=re.MULTILINE)

    # Post-process to remove brackets/nulls for triggers
    # Replace "push: {}" or "push: []" or "push: null" with "push:"
    # We do this for push and pull_request and workflow_dispatch
    for trigger in ['push', 'pull_request', 'workflow_dispatch', 'schedule']:
        # Match '  push: {}' or similar
        # Since we use 2 space indent in PyYAML default or based on flow style
        # We need to be careful with regex.
        # But yaml dump of {'push': {}} with default_flow_style=False usually outputs:
        # on:
        #   push: {}

        # Regex to find key followed by empty dict/list/null
        yaml_output = re.sub(rf"(\s+){trigger}: {{}}", rf"\1{trigger}:", yaml_output)
        yaml_output = re.sub(rf"(\s+){trigger}: \[\]", rf"\1{trigger}:", yaml_output)
        yaml_output = re.sub(rf"(\s+){trigger}: null", rf"\1{trigger}:", yaml_output)

    # Post-process for spacing
    # Add newline before 'jobs:'
    yaml_output = yaml_output.replace('\njobs:', '\n\njobs:')

    lines = yaml_output.splitlines()
    new_lines = []
    in_jobs = False

    convert_next = False
    indent_str = ""

    for i, line in enumerate(lines):
        if line.startswith('jobs:'):
            in_jobs = True
            new_lines.append(line)
            continue

        if in_jobs and line.startswith('  ') and not line.startswith('    '):
            # This is likely a job key (indentation 2 spaces)
            # Check if it's a key
            if ':' in line:
                new_lines.append('') # Add empty line before job

        # Handle _comment field which appears as "- _comment: ..."
        # We transform this into a comment line "# ..."
        # and shift the next line (which should be the start of the list item) to have the dash.
        match = re.match(r'^(\s*)- _comment: (.*)', line)
        if match:
            indent_str = match.group(1)
            comment_text = match.group(2)

            # Remove quotes if present
            if (comment_text.startswith('"') and comment_text.endswith('"')) or \
               (comment_text.startswith("'") and comment_text.endswith("'")):
                comment_text = comment_text[1:-1]

            # "before starting the -name, leave a space of 1 line"
            # We interpret this as leaving a space before the block start (which is now the comment)
            new_lines.append('')
            new_lines.append(f'{indent_str}# {comment_text}')

            convert_next = True
            continue

        if convert_next:
            # This line should start with indent_str + 2 spaces
            expected_prefix = indent_str + '  '
            if line.startswith(expected_prefix):
                # Replace the spaces with '- '
                # We want the dash to be at the same indentation level as the original dash
                # So we replace (indent_str + '  ') with (indent_str + '- ')
                new_line = indent_str + '- ' + line[len(expected_prefix):]
                new_lines.append(new_line)
            else:
                # Should not happen if yaml structure is consistent, but fallback
                new_lines.append(line)

            convert_next = False
            continue

        # "before starting the -name, leave a space of 1 line"
        # Only do this if we haven't already handled it via _comment
        if line.strip().startswith('- name:'):
             new_lines.append('')

        new_lines.append(line)

    final_output = '\n'.join(new_lines)

    # Clean up double empty lines if any
    final_output = re.sub(r'\n{3,}', '\n\n', final_output)

    return jsonify({'yaml': final_output})

if __name__ == '__main__':
    # Debug mode should be False in production contexts
    app.run(host='0.0.0.0', debug=False, port=5006)
