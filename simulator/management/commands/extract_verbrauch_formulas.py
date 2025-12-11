"""
Extract Verbrauch Formulas from Python Code
============================================

This script parses verbrauch_calculations.py and extracts all formulas
into a dictionary format that can be imported into the database.

It converts code like:
    if self.code == "1.1.1.1":
        # 1.1.1.1 = 1.1.0 * 1.1.1%
        return base_1_1.status * (percent_1_1_1.status / 100.0)

Into:
    '1.1.1.1': {
        'formula': 'VerbrauchData_1.1 * VerbrauchData_1.1.1 / 100',
        'description': '1.1.1.1 = 1.1.0 * 1.1.1%',
        'is_fixed': False,
    }
"""

import re
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Formula storage
VERBRAUCH_STATUS_FORMULAS = {}
VERBRAUCH_ZIEL_FORMULAS = {}


def extract_formulas_from_file(filepath):
    """Extract all formulas from verbrauch_calculations.py"""
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Pattern to find elif blocks with code
    code_pattern = r'elif self\.code == "([^"]+)":'
    comment_pattern = r'#\s*(.+?)(?:\n|$)'
    
    # Find all code blocks
    matches = list(re.finditer(code_pattern, content))
    
    for i, match in enumerate(matches):
        code = match.group(1)
        start_pos = match.end()
        
        # Find end of this block (next elif or end of function)
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(content)
        
        block = content[start_pos:end_pos]
        
        # Extract comment (formula description)
        comment_match = re.search(comment_pattern, block)
        description = comment_match.group(1).strip() if comment_match else ""
        
        # Try to extract formula from the code
        formula = extract_formula_from_code(code, block, description)
        
        if formula:
            VERBRAUCH_STATUS_FORMULAS[code] = {
                'name': f'Verbrauch calculation for {code}',
                'formula': formula,
                'description': description,
                'is_fixed': False,
            }
            print(f"✓ Extracted {code}: {formula}")
        else:
            print(f"⚠ Could not extract formula for {code}: {description}")


def extract_formula_from_code(code, block, description):
    """
    Convert Python calculation code to formula string.
    
    Examples:
    - base * percent / 100 → VerbrauchData_X * VerbrauchData_Y / 100
    - value1 + value2 + value3 → VerbrauchData_X + VerbrauchData_Y + VerbrauchData_Z
    """
    
    # Try to parse from comment first (most reliable)
    if '=' in description:
        # Extract formula from comment like "1.1.1.1 = 1.1.0 * 1.1.1%"
        parts = description.split('=', 1)
        if len(parts) == 2:
            formula_text = parts[1].strip()
            
            # Convert references to VerbrauchData_ format
            formula_text = convert_formula_references(formula_text)
            return formula_text
    
    # Fallback: try to extract from actual code patterns
    # Look for simple multiplication patterns
    mult_pattern = r'return\s+\S+\.status\s*\*\s*\(\S+\.status\s*/\s*100\.0\)'
    if re.search(mult_pattern, block):
        # Extract variable names
        var_matches = re.findall(r'code="([^"]+)"', block)
        if len(var_matches) >= 2:
            return f'VerbrauchData_{var_matches[0]} * VerbrauchData_{var_matches[1]} / 100'
    
    # Look for addition patterns
    add_pattern = r'return\s+\S+\s*\+\s*\S+'
    if re.search(add_pattern, block):
        var_matches = re.findall(r'code="([^"]+)"', block)
        if len(var_matches) >= 2:
            return ' + '.join([f'VerbrauchData_{v}' for v in var_matches])
    
    return None


def convert_formula_references(formula_text):
    """
    Convert formula references to VerbrauchData_ format.
    
    Examples:
    - "1.1.0 * 1.1.1%" → "VerbrauchData_1.1 * VerbrauchData_1.1.1 / 100"
    - "1.1.1.3 + 1.2.5 + 1.3.5" → "VerbrauchData_1.1.1.3 + VerbrauchData_1.2.5 + VerbrauchData_1.3.5"
    """
    
    # Handle percentage signs (convert X% to X/100)
    formula_text = re.sub(r'(\d+(?:\.\d+)*)\s*%', r'VerbrauchData_\1 / 100', formula_text)
    
    # Handle regular number references (but not division results like /100)
    # Match patterns like "1.1.0" or "1.2.3" but not if already prefixed
    formula_text = re.sub(
        r'(?<!VerbrauchData_)(?<!/)\b(\d+(?:\.\d+)+)\b(?!\s*/\s*100)',
        r'VerbrauchData_\1',
        formula_text
    )
    
    # Clean up "1.1.0" style codes (convert to just "1.1")
    formula_text = re.sub(r'VerbrauchData_(\d+)\.(\d+)\.0\b', r'VerbrauchData_\1.\2', formula_text)
    
    return formula_text


def save_formulas_to_python_file(output_file):
    """Save extracted formulas to a Python file"""
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('"""\n')
        f.write('VERBRAUCH FORMULAS - Extracted from verbrauch_calculations.py\n')
        f.write('=' * 80 + '\n')
        f.write(f'Total formulas extracted: {len(VERBRAUCH_STATUS_FORMULAS)}\n')
        f.write('"""\n\n')
        
        f.write('VERBRAUCH_STATUS_FORMULAS = {\n')
        for code in sorted(VERBRAUCH_STATUS_FORMULAS.keys()):
            formula_def = VERBRAUCH_STATUS_FORMULAS[code]
            f.write(f"    '{code}': {{\n")
            f.write(f"        'name': '{formula_def['name']}',\n")
            f.write(f"        'formula': '{formula_def['formula']}',\n")
            f.write(f"        'description': '{formula_def['description']}',\n")
            f.write(f"        'is_fixed': {formula_def['is_fixed']},\n")
            f.write(f"    }},\n")
        f.write('}\n\n')
        
        f.write('VERBRAUCH_ZIEL_FORMULAS = VERBRAUCH_STATUS_FORMULAS.copy()\n')
        f.write('# Ziel formulas use same structure, calculated separately\n')


if __name__ == '__main__':
    # Path to verbrauch_calculations.py
    verbrauch_file = os.path.join(
        os.path.dirname(__file__), 
        '..', '..', '..', 
        'simulator', 
        'verbrauch_calculations.py'
    )
    
    print("=" * 80)
    print("Extracting Verbrauch Formulas")
    print("=" * 80)
    print(f"Source: {verbrauch_file}")
    print()
    
    extract_formulas_from_file(verbrauch_file)
    
    print()
    print("=" * 80)
    print(f"Total formulas extracted: {len(VERBRAUCH_STATUS_FORMULAS)}")
    print("=" * 80)
    
    # Save to output file
    output_file = os.path.join(
        os.path.dirname(__file__),
        '..',  '..',  '..',
        'verbrauch_formulas_extracted.py'
    )
    save_formulas_to_python_file(output_file)
    print(f"\n✓ Formulas saved to: {output_file}")
