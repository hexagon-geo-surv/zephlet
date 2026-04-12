#!/usr/bin/env python3
"""
Adapter Generator for Zephyr Zephlets
Generates adapter boilerplate from zephlet proto files.

Two modes:
  Interactive (default): prompts user to select zephlets and fields
  Non-interactive (--non-interactive): for build-time re-generation

Generates two files:
  <adapter>.c       - auto-generated dispatcher (build dir or output dir)
  <adapter>_impl.c  - user-editable callbacks (output dir, smart-updated)
"""

import os
import re
import sys
import argparse
from pathlib import Path
from proto_schema_parser import Parser
from jinja2 import Environment, FileSystemLoader

try:
    import tree_sitter_c as tsc
    from tree_sitter import Language, Parser as TSParser
    HAS_TREE_SITTER = True
except ImportError:
    HAS_TREE_SITTER = False


def camel_to_snake(name):
    """Convert CamelCase to snake_case"""
    result = []
    for i, char in enumerate(name):
        if char.isupper() and i > 0:
            if name[i-1].islower() or (i < len(name) - 1 and name[i+1].islower()):
                result.append('_')
        result.append(char.lower())
    return ''.join(result)


def snake_to_camel(name):
    """Convert snake_case to CamelCase"""
    return ''.join(word.capitalize() for word in name.split('_'))


def _find_zephlet_msg(messages):
    """Find the main zephlet message in a list of proto messages."""
    # Old pattern: Msg*Zephlet or MsgZlet*
    for message in messages:
        if message.name.startswith('Msg') and (
            message.name.endswith('Zephlet') or message.name.startswith('MsgZlet')
        ):
            return message
    # New pattern: message with Invoke + Report sub-messages
    skip_names = {'_', 'Empty', 'ZephletStatus', 'ZephletResult'}
    for message in messages:
        if message.name in skip_names:
            continue
        nested_names = set()
        for elem in message.elements:
            if hasattr(elem, 'name') and elem.__class__.__name__ == 'Message':
                nested_names.add(elem.name)
        if 'Invoke' in nested_names and 'Report' in nested_names:
            return message
    return None


def _extract_report_metadata(zephlet_msg):
    """Extract Report oneof name and fields from a zephlet message."""
    report_msg = None
    for element in zephlet_msg.elements:
        if hasattr(element, 'name') and element.__class__.__name__ == 'Message':
            if element.name == 'Report':
                report_msg = element
                break

    if not report_msg:
        return None, []

    for element in report_msg.elements:
        if element.__class__.__name__ == 'OneOf':
            fields = [f for f in element.elements if hasattr(f, 'name')]
            return element.name, fields

    return None, []


def discover_zephlets(zephlets_path, generated_protos_path=None):
    """
    Scan zephlets/* for proto files and extract metadata.
    If generated_protos_path is provided, uses generated protos (which contain
    Invoke/Report) instead of source base files.
    Returns: list of dicts with zephlet metadata
    """
    zephlets = []
    zephlets_dir = Path(zephlets_path)

    if not zephlets_dir.exists():
        print(f"Error: Zephlets path '{zephlets_path}' does not exist")
        return zephlets

    for zephlet_dir in zephlets_dir.iterdir():
        if not zephlet_dir.is_dir():
            continue

        zephlet_name = zephlet_dir.name

        if zephlet_name in ['shared']:
            continue

        # Find the proto to parse: prefer generated proto if available
        proto_path = None
        if generated_protos_path:
            gen_dir = Path(generated_protos_path)
            # Generated protos are at <build>/modules/zlet_<name>/zlet_<name>.proto
            for pattern in [
                gen_dir / f"zlet_{zephlet_name}" / f"zlet_{zephlet_name}.proto",
                gen_dir / f"{zephlet_name}" / f"zlet_{zephlet_name}.proto",
                gen_dir / f"zlet_{zephlet_name}" / f"{zephlet_name}.proto",
            ]:
                if pattern.exists():
                    proto_path = pattern
                    break

        # Fall back to source proto
        if not proto_path:
            for name in [f"zlet_{zephlet_name}.proto", f"{zephlet_name}_zephlet.proto", f"{zephlet_name}.proto"]:
                candidate = zephlet_dir / name
                if candidate.exists():
                    proto_path = candidate
                    break

        if not proto_path:
            continue

        try:
            with open(proto_path, 'r') as f:
                proto_content = f.read()

            parser = Parser()
            parsed = parser.parse(proto_content)

            messages = [e for e in parsed.file_elements
                        if hasattr(e, 'name') and e.__class__.__name__ == 'Message']

            zephlet_msg = _find_zephlet_msg(messages)
            if not zephlet_msg:
                continue

            report_oneof_name, report_fields = _extract_report_metadata(zephlet_msg)
            if report_fields:
                zephlets.append({
                    'name': zephlet_name,
                    'proto_path': str(proto_path),
                    'proto_msg_name': zephlet_msg.name,
                    'pb_prefix': camel_to_snake(zephlet_msg.name),
                    'report_oneof': report_oneof_name,
                    'report_fields': report_fields
                })

        except Exception as e:
            print(f"Warning: Failed to parse {proto_path}: {e}")
            continue

    return sorted(zephlets, key=lambda z: z['name'])


def select_zephlets_interactive(zephlets):
    """Interactive zephlet selection. Returns: (origin_dict, dest_dict)"""
    if not zephlets:
        print("Error: No zephlets found")
        sys.exit(1)

    print("\nAvailable zephlets:")
    for i, zephlet in enumerate(zephlets, 1):
        print(f"  {i}. {zephlet['name']}")

    while True:
        try:
            origin_idx = int(input("\nSelect origin zephlet (number): ")) - 1
            if 0 <= origin_idx < len(zephlets):
                origin = zephlets[origin_idx]
                break
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            print("\nCancelled")
            sys.exit(1)

    dest_zephlets = [z for i, z in enumerate(zephlets) if i != origin_idx]
    print(f"\nAvailable destination zephlets (excluding {origin['name']}):")
    for i, zephlet in enumerate(dest_zephlets, 1):
        print(f"  {i}. {zephlet['name']}")

    while True:
        try:
            dest_idx = int(input("\nSelect destination zephlet (number): ")) - 1
            if 0 <= dest_idx < len(dest_zephlets):
                dest = dest_zephlets[dest_idx]
                break
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            print("\nCancelled")
            sys.exit(1)

    return origin, dest


def filter_report_fields_interactive(origin):
    """Let user select which report fields to handle. Returns: filtered list."""
    fields = origin['report_fields']
    if not fields:
        return []

    print(f"\nReport fields from {origin['name']} zephlet:")
    for i, field in enumerate(fields, 1):
        print(f"  {i}. {field.name}")

    print("\nSelect fields to handle (e.g., '1,3' or 'all' for all fields):")
    while True:
        try:
            selection = input("> ").strip().lower()
            if selection == 'all':
                return fields

            indices = [int(x.strip()) - 1 for x in selection.split(',')]
            selected = [fields[i] for i in indices if 0 <= i < len(fields)]
            if selected:
                return selected
            print("Invalid selection")
        except (ValueError, KeyboardInterrupt):
            print("\nCancelled")
            sys.exit(1)


def filter_report_fields_by_names(origin, field_names):
    """
    Filter report fields by comma-separated names (non-interactive mode).
    Returns: filtered list of report fields
    """
    fields = origin['report_fields']
    names = [n.strip() for n in field_names.split(',')]
    selected = [f for f in fields if f.name in names]

    if not selected:
        print(f"Warning: No matching fields for '{field_names}'")
        print(f"Available: {[f.name for f in fields]}")

    return selected


def suggest_destination_api(destination):
    """Parse destination proto to suggest available API calls. Returns: list of invoke field names."""
    try:
        with open(destination['proto_path'], 'r') as f:
            proto_content = f.read()

        parser = Parser()
        parsed = parser.parse(proto_content)

        messages = [e for e in parsed.file_elements
                    if hasattr(e, 'name') and e.__class__.__name__ == 'Message']

        zephlet_msg = _find_zephlet_msg(messages)
        if not zephlet_msg:
            return []

        invoke_msg = None
        for element in zephlet_msg.elements:
            if hasattr(element, 'name') and element.__class__.__name__ == 'Message':
                if element.name == 'Invoke':
                    invoke_msg = element
                    break

        if not invoke_msg:
            return []

        invoke_fields = []
        for element in invoke_msg.elements:
            if element.__class__.__name__ == 'OneOf':
                for field in element.elements:
                    if hasattr(field, 'name'):
                        invoke_fields.append(field.name)
                break

        return invoke_fields

    except Exception as e:
        print(f"Warning: Failed to parse destination proto: {e}")
        return []


def build_adapter_context(origin, dest, selected_fields, dest_api_suggestions):
    """Build template context for adapter generation."""
    origin_name = origin['name']
    dest_name = dest['name']

    origin_camel = snake_to_camel(origin_name)
    dest_camel = snake_to_camel(dest_name)

    origin_base = origin_name
    if origin_name.startswith('zlet_'):
        origin_base = origin_name[5:]
    elif origin_name.endswith('_zephlet'):
        origin_base = origin_name[:-8]

    dest_base = dest_name
    if dest_name.startswith('zlet_'):
        dest_base = dest_name[5:]
    elif dest_name.endswith('_zephlet'):
        dest_base = dest_name[:-8]

    adapter_name = f"{snake_to_camel(origin_base)}+{snake_to_camel(dest_base)}_zlet_adapter"

    # Build set of selected field names for template comparison
    selected_field_names = {f.name for f in selected_fields}

    # Nanopb C prefix derived from proto message name
    origin_pb_prefix = origin.get('pb_prefix', f"msg_zlet_{origin_base}")
    origin_pb_prefix_upper = origin_pb_prefix.upper()
    dest_pb_prefix = dest.get('pb_prefix', f"msg_zlet_{dest_base}")
    dest_pb_prefix_upper = dest_pb_prefix.upper()

    context = {
        'origin_zephlet': origin_name,
        'origin_zephlet_upper': origin_name.upper(),
        'origin_zephlet_camel': origin_camel,
        'origin_base': origin_base,
        'origin_base_upper': origin_base.upper(),
        'origin_pb_prefix': origin_pb_prefix,
        'origin_pb_prefix_upper': origin_pb_prefix_upper,
        'origin_report_oneof': origin['report_oneof'],
        'origin_report_fields': origin['report_fields'],
        'selected_report_fields': selected_fields,
        'selected_field_names': selected_field_names,
        'dest_zephlet': dest_name,
        'dest_zephlet_upper': dest_name.upper(),
        'dest_zephlet_camel': dest_camel,
        'dest_base': dest_base,
        'dest_base_upper': dest_base.upper(),
        'dest_pb_prefix': dest_pb_prefix,
        'dest_pb_prefix_upper': dest_pb_prefix_upper,
        'adapter_name': adapter_name,
        'adapter_config': f"{origin_base.upper()}_TO_{dest_base.upper()}_ADAPTER",
        'listener_name': f"lis_{origin_name}_to_{dest_name}_adapter",
        'function_name': f"{origin_name}_to_{dest_name}_adapter",
        'callback_prefix': f"{origin_name}_to_{dest_name}",
        'dest_api_suggestions': dest_api_suggestions
    }

    return context


def create_jinja_env(templates_dir):
    """Create Jinja2 environment with custom filters."""
    env = Environment(loader=FileSystemLoader(templates_dir))
    env.filters['camel_to_snake'] = camel_to_snake
    env.filters['upper'] = str.upper
    env.filters['lower'] = str.lower
    return env


def render_adapter_auto(context, output_dir, templates_dir):
    """Render auto-generated adapter.c file."""
    env = create_jinja_env(templates_dir)
    template = env.get_template('adapter.c.jinja')
    adapter_content = template.render(context)

    adapter_path = Path(output_dir) / f"{context['adapter_name']}.c"
    adapter_path.parent.mkdir(parents=True, exist_ok=True)

    with open(adapter_path, 'w') as f:
        f.write(adapter_content)

    print(f"Generated (auto): {adapter_path}")
    return adapter_path


def render_adapter_impl(context, output_dir, templates_dir):
    """Render adapter_impl.c bootstrap template (only if file doesn't exist)."""
    env = create_jinja_env(templates_dir)
    template = env.get_template('adapter_impl.c.jinja')
    impl_content = template.render(context)

    impl_path = Path(output_dir) / f"{context['adapter_name']}_impl.c"
    impl_path.parent.mkdir(parents=True, exist_ok=True)

    if impl_path.exists():
        print(f"Skipping: {impl_path} already exists (use smart-update instead)")
        return impl_path

    with open(impl_path, 'w') as f:
        f.write(impl_content)

    print(f"Generated (impl): {impl_path}")
    return impl_path


# ---------------------------------------------------------------------------
# Tree-sitter based smart update for _impl.c
# ---------------------------------------------------------------------------

REMOVED_BEGIN_MARKER = "/* ZLET_CODEGEN_REMOVED_BEGIN: {} */"
REMOVED_END_MARKER = "/* ZLET_CODEGEN_REMOVED_END: {} */"


def _get_ts_parser():
    """Create tree-sitter parser for C."""
    lang = Language(tsc.language())
    return TSParser(lang)


def _get_function_name(func_def_node):
    """
    Extract function name from a function_definition node.
    Traverses: function_definition -> function_declarator -> identifier
    """
    declarator = func_def_node.child_by_field_name('declarator')
    if declarator and declarator.type == 'function_declarator':
        name_node = declarator.child_by_field_name('declarator')
        if name_node and name_node.type == 'identifier':
            return name_node.text.decode()
    return None


def _find_callback_functions(root_node):
    """
    Find all function definitions matching the callback naming pattern.
    Uses tree-sitter node traversal on the parsed AST.
    Returns: dict of {func_name: func_def_node}
    """
    result = {}
    for child in root_node.children:
        if child.type == 'function_definition':
            name = _get_function_name(child)
            if name and '_on_report_' in name:
                result[name] = child
    return result


def _find_last_toplevel_node(root_node):
    """
    Find the last top-level node for determining insertion position.
    Returns: the last child node or None
    """
    children = root_node.children
    if children:
        return children[-1]
    return None


def _find_commented_callbacks(content):
    """
    Find callback function names that are commented out with ZLET_CODEGEN_REMOVED markers.
    Returns: set of function names
    """
    pattern = r'/\* ZLET_CODEGEN_REMOVED_BEGIN: (\S+) \*/'
    return set(re.findall(pattern, content))


def _uncomment_callback(content, func_name):
    """Remove ZLET_CODEGEN_REMOVED markers and // comment prefixes to restore a callback."""
    begin_marker = REMOVED_BEGIN_MARKER.format(func_name)
    end_marker = REMOVED_END_MARKER.format(func_name)

    begin_idx = content.find(begin_marker)
    end_idx = content.find(end_marker)
    if begin_idx == -1 or end_idx == -1:
        return content

    end_idx += len(end_marker)

    # Extract the block between markers
    block = content[begin_idx:end_idx]

    # Remove markers, then strip // prefix from each line
    inner_lines = []
    for line in block.split('\n'):
        stripped = line.strip()
        if stripped == begin_marker.strip() or stripped == end_marker.strip():
            continue
        if line.startswith('// '):
            inner_lines.append(line[3:])
        elif line.startswith('//'):
            inner_lines.append(line[2:])
        else:
            inner_lines.append(line)
    inner = '\n'.join(inner_lines).strip()

    # Replace the full block (including any surrounding newlines)
    actual_start = begin_idx
    if actual_start > 0 and content[actual_start - 1] == '\n':
        actual_start -= 1

    actual_end = end_idx
    if actual_end < len(content) and content[actual_end] == '\n':
        actual_end += 1

    content = content[:actual_start] + '\n' + inner + '\n' + content[actual_end:]
    return content


def _render_callback_skeleton(func_name, field, context, templates_dir):
    """Render a callback function skeleton using Jinja template."""
    env = create_jinja_env(templates_dir)
    template = env.get_template('adapter_impl_callback.c.jinja')
    return template.render(
        callback_prefix=context['callback_prefix'],
        field_name=field.name,
        origin_base=context['origin_base'],
        origin_pb_prefix=context['origin_pb_prefix'],
        dest_base=context.get('dest_base', ''),
        dest_api_suggestions=context.get('dest_api_suggestions', []),
    )


def _extract_field_from_callback_name(func_name, callback_prefix):
    """
    Extract the field name from a callback function name.
    E.g., 'tick_to_ui_on_report_events' -> 'events'
    """
    prefix = f"{callback_prefix}_on_report_"
    if func_name.startswith(prefix):
        return func_name[len(prefix):]
    return None


def smart_update_impl(impl_path, context, templates_dir):
    """
    Parse existing _impl.c with tree-sitter queries to detect, add, and
    comment/uncomment callbacks based on selected_report_fields.
    """
    impl_path = Path(impl_path)
    if not impl_path.exists():
        return False

    if not HAS_TREE_SITTER:
        print("Warning: tree-sitter not available, skipping smart update")
        return False

    source = impl_path.read_bytes()
    parser = _get_ts_parser()
    tree = parser.parse(source)

    # Query existing callback functions
    existing_funcs = _find_callback_functions(tree.root_node)

    # Find commented-out callbacks
    content = impl_path.read_text()
    commented_funcs = _find_commented_callbacks(content)

    modified = False
    callback_prefix = context['callback_prefix']
    selected_fields = context['selected_report_fields']
    selected_names = {f.name for f in selected_fields}

    # Phase 1: Add or uncomment selected callbacks
    for field in selected_fields:
        func_name = f"{callback_prefix}_on_report_{field.name}"

        if func_name in commented_funcs:
            content = _uncomment_callback(content, func_name)
            modified = True
            print(f"  Uncommented: {func_name}")
        elif func_name not in existing_funcs:
            # Re-parse to get current tree after potential modifications
            if modified:
                new_tree = parser.parse(content.encode())
                last_node = _find_last_toplevel_node(new_tree.root_node)
            else:
                last_node = _find_last_toplevel_node(tree.root_node)

            skeleton = _render_callback_skeleton(func_name, field, context, templates_dir)
            if last_node:
                insert_pos = last_node.end_byte
                content = content[:insert_pos] + '\n\n' + skeleton + content[insert_pos:]
            else:
                content = content.rstrip() + '\n\n' + skeleton
            modified = True
            print(f"  Added: {func_name}")

    # Phase 2: Comment out callbacks no longer in selected fields
    for func_name, node in existing_funcs.items():
        field_name = _extract_field_from_callback_name(func_name, callback_prefix)
        if field_name is None:
            continue
        if field_name not in selected_names:
            begin_marker = REMOVED_BEGIN_MARKER.format(func_name)
            if begin_marker not in content:
                end_marker = REMOVED_END_MARKER.format(func_name)
                # Use node byte range to extract function text
                func_text = source[node.start_byte:node.end_byte].decode()
                # Comment out each line with //
                commented_lines = '\n'.join(
                    f"// {line}" if line.strip() else '//'
                    for line in func_text.split('\n')
                )
                replacement = (
                    f"{begin_marker}\n"
                    f"{commented_lines}\n"
                    f"{end_marker}"
                )
                # Find the function in current content text (may have shifted)
                func_start = content.find(func_text)
                if func_start != -1:
                    content = content[:func_start] + replacement + content[func_start + len(func_text):]
                    modified = True
                    print(f"  Commented out: {func_name}")

    if modified:
        impl_path.write_text(content)
        print(f"Updated: {impl_path}")

    return modified


# ---------------------------------------------------------------------------
# Kconfig and CMakeLists.txt update (unchanged from original)
# ---------------------------------------------------------------------------

def update_kconfig(kconfig_path, kconfig_entry):
    """Update adapters/Kconfig with new entry."""
    kconfig_file = Path(kconfig_path)

    if not kconfig_file.exists():
        print(f"\nWarning: {kconfig_path} not found")
        print("Manual step required: Create Kconfig file with:")
        print(kconfig_entry)
        return False

    try:
        with open(kconfig_file, 'r') as f:
            lines = f.readlines()

        config_name = kconfig_entry.split('\n')[0].split()[1]
        if any(config_name in line for line in lines):
            print(f"Info: {config_name} already exists in Kconfig, skipping")
            return True

        insert_idx = -1
        for i, line in enumerate(lines):
            if line.strip().startswith('module =') or line.strip().startswith('module='):
                insert_idx = i
                break

        if insert_idx == -1:
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith('endif'):
                    insert_idx = i
                    break

        if insert_idx == -1:
            with open(kconfig_file, 'a') as f:
                f.write('\n' + kconfig_entry + '\n')
        else:
            if insert_idx > 0 and lines[insert_idx - 1].strip():
                lines.insert(insert_idx, '\n')
                insert_idx += 1
            lines.insert(insert_idx, kconfig_entry + '\n')
            if insert_idx + 1 < len(lines) and (
                lines[insert_idx + 1].strip().startswith('module =') or
                lines[insert_idx + 1].strip().startswith('module=')
            ):
                lines.insert(insert_idx + 1, '\n')
            with open(kconfig_file, 'w') as f:
                f.writelines(lines)

        print(f"Updated: {kconfig_path}")
        return True

    except Exception as e:
        print(f"\nWarning: Failed to update {kconfig_path}: {e}")
        print("Manual step required: Add to Kconfig:")
        print(kconfig_entry)
        return False


def update_cmakelists(cmake_path, context):
    """Update adapters/CMakeLists.txt with zephlet_adapter_generate() call."""
    cmake_file = Path(cmake_path)
    origin_base = context['origin_base']
    dest_base = context['dest_base']
    field_names = ' '.join(f.name for f in context['selected_report_fields'])
    new_line = f'    zephlet_adapter_generate(ORIGIN {origin_base} DEST {dest_base} REPORTS {field_names})\n'

    if not cmake_file.exists():
        print(f"\nWarning: {cmake_path} not found")
        print(f"Manual step required: Add to CMakeLists.txt:")
        print(f'    {new_line.strip()}')
        return False

    try:
        with open(cmake_file, 'r') as f:
            lines = f.readlines()

        if any(context['adapter_name'] in line for line in lines):
            print(f"Info: {context['adapter_name']} already exists in CMakeLists.txt, skipping")
            return True

        # Find insertion point: after last zephlet_adapter_generate or zephyr_library_sources
        insert_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if 'zephlet_adapter_generate' in lines[i] or 'zephyr_library_sources' in lines[i]:
                insert_idx = i + 1
                break

        if insert_idx == -1:
            for i in range(len(lines) - 1, -1, -1):
                if lines[i].strip().startswith('endif()'):
                    insert_idx = i
                    if i > 0 and lines[i-1].strip():
                        lines.insert(i, '\n')
                        insert_idx += 1
                    break

        if insert_idx == -1:
            with open(cmake_file, 'a') as f:
                f.write(new_line)
        else:
            lines.insert(insert_idx, new_line)
            with open(cmake_file, 'w') as f:
                f.writelines(lines)

        print(f"Updated: {cmake_path}")
        return True

    except Exception as e:
        print(f"\nWarning: Failed to update {cmake_path}: {e}")
        print(f"Manual step required: Add to CMakeLists.txt:")
        print(f'    {new_line.strip()}')
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Generate adapter boilerplate from zephlet protos'
    )
    parser.add_argument('--zephlets-path', required=True,
                        help='Path to zephlets directory')
    parser.add_argument('--output-dir', required=True,
                        help='Output directory for adapter impl files (source dir)')
    parser.add_argument('--build-dir', default=None,
                        help='Output directory for auto-generated adapter.c (build dir). '
                             'If not set, adapter.c is written to output-dir.')
    parser.add_argument('--non-interactive', action='store_true',
                        help='Non-interactive mode for build-time re-generation')
    parser.add_argument('--origin', default=None,
                        help='Origin zephlet name (non-interactive mode)')
    parser.add_argument('--dest', default=None,
                        help='Destination zephlet name (non-interactive mode)')
    parser.add_argument('--fields', default=None,
                        help='Comma-separated report field names to handle (non-interactive mode)')
    parser.add_argument('--impl-only', action='store_true',
                        help='Only generate _impl.c (bootstrap mode)')
    parser.add_argument('--generated-protos-path', default=None,
                        help='Path to build dir containing generated protos '
                             '(with Invoke/Report). Falls back to source protos.')

    args = parser.parse_args()

    script_dir = Path(__file__).parent
    templates_dir = script_dir / 'templates'

    if not templates_dir.exists():
        print(f"Error: Templates directory not found: {templates_dir}")
        sys.exit(1)

    print(f"Scanning zephlets in {args.zephlets_path}...")
    zephlets = discover_zephlets(args.zephlets_path, args.generated_protos_path)

    if not zephlets:
        print("No zephlets found")
        sys.exit(1)

    print(f"Found {len(zephlets)} zephlets")

    if args.non_interactive:
        if not args.origin or not args.dest or not args.fields:
            print("Error: --origin, --dest, and --fields required in non-interactive mode")
            sys.exit(1)

        origin = next((z for z in zephlets if z['name'] == args.origin), None)
        dest = next((z for z in zephlets if z['name'] == args.dest), None)

        if not origin:
            print(f"Error: Origin zephlet '{args.origin}' not found")
            sys.exit(1)
        if not dest:
            print(f"Error: Destination zephlet '{args.dest}' not found")
            sys.exit(1)

        selected_fields = filter_report_fields_by_names(origin, args.fields)
    else:
        origin, dest = select_zephlets_interactive(zephlets)
        selected_fields = filter_report_fields_interactive(origin)

    dest_api_suggestions = suggest_destination_api(dest)
    context = build_adapter_context(origin, dest, selected_fields, dest_api_suggestions)

    print(f"\nGenerating adapter: {context['adapter_name']}")

    output_dir = Path(args.output_dir)

    if args.impl_only:
        impl_path = output_dir / "src" / f"{context['adapter_name']}_impl.c"
        if impl_path.exists():
            print(f"Smart-updating: {impl_path}")
            smart_update_impl(impl_path, context, templates_dir)
        else:
            render_adapter_impl(context, output_dir / "src", templates_dir)
    else:
        if args.build_dir:
            render_adapter_auto(context, Path(args.build_dir), templates_dir)

        impl_path = output_dir / "src" / f"{context['adapter_name']}_impl.c"
        if impl_path.exists():
            print(f"Smart-updating: {impl_path}")
            smart_update_impl(impl_path, context, templates_dir)
        else:
            render_adapter_impl(context, output_dir / "src", templates_dir)

        if not args.non_interactive:
            env = create_jinja_env(templates_dir)
            kconfig_template = env.get_template('adapter_kconfig.jinja')
            kconfig_entry = kconfig_template.render(context)

            kconfig_path = output_dir / 'Kconfig'
            update_kconfig(kconfig_path, kconfig_entry)

            cmake_path = output_dir / 'CMakeLists.txt'
            update_cmakelists(cmake_path, context)

    print(f"\nAdapter generation complete!")

    if not args.non_interactive:
        print(f"\nNext steps:")
        impl_file = f"{context['adapter_name']}_impl.c"
        print(f"1. Implement callbacks in: {output_dir / 'src' / impl_file}")
        print(f"2. Build: just c b r")
        print(f"\nNote: Adapter is enabled by default (CONFIG_{context['adapter_config']}=y)")


if __name__ == '__main__':
    main()
