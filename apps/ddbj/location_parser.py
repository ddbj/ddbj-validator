"""DDBJ location 文字列の解析（parser.py から分離）。"""
import re
from Bio.SeqFeature import (
    SeqFeature, FeatureLocation, ExactPosition, BeforePosition, AfterPosition,
    CompoundLocation, BetweenPosition, OneOfPosition, WithinPosition
)


class LocationParseError(Exception):
    pass

class LocationRangeError(LocationParseError):
    pass

class LocationPartialDescriptorError(LocationParseError):
    pass


def _parse_location_string(loc_str, seq_length=0, default_strand=1):
    if not loc_str: return None
    
    # 外部参照アクセッション（例: AB000001.1:）の数値を誤検知しないよう一時的に除外
    loc_no_acc = re.sub(r'[a-zA-Z0-9_.]+:', '', loc_str)
    
    match = re.search(r'\b(0\d*)\b', loc_no_acc)
    if match:
        matched_val = match.group(1)
        if matched_val == "0":
            raise LocationParseError("Position coordinate cannot be '0' (coordinates must be 1-based).")
        else:
            raise LocationParseError(f"Zero-padded position numbers are not allowed. (Found: '{matched_val}')")

    if "order(" in loc_str:
        raise LocationParseError("The 'order' operator is not supported for DDBJ submissions.")
                
    if loc_str.count("join(") > 1:
        raise LocationParseError("Nested 'join' is not allowed.")
        
    strand = default_strand
    
    if loc_str.startswith("complement(") and loc_str.endswith(")"):
        strand = -1
        loc_str = loc_str[11:-1]
        
    if loc_str.startswith("join(") and loc_str.endswith(")"):
        inner_loc = loc_str[5:-1] 

        parts = [p.strip() for p in inner_loc.split(",")]
        if len(parts) == 1:
            raise LocationParseError("join() with a single element is invalid.")

        for i, part in enumerate(parts):
            if i > 0 and '<' in part:
                raise LocationPartialDescriptorError("Invalid location. Partial operator '<' must only appear at the start of the entire location.")
            if i < len(parts) - 1 and '>' in part:
                raise LocationPartialDescriptorError("Invalid location. Partial operator '>' must only appear at the end of the entire location.")

        explicit_complements = ["complement(" in p for p in parts]
        
        if all(explicit_complements):
            raise LocationParseError("Found complement() inside join(). Use complement(join(...)) instead.")

        locations = []
        for part in parts:
            parsed_loc = _parse_location_string(part, seq_length=seq_length, default_strand=strand)
            locations.append(parsed_loc)
            
        out_of_order_err = None
        suggest_slippage = False
        join_diffs = [] 
        
        local_locations = [loc for loc in locations if getattr(loc, 'ref', None) is None]
        
        seen_intervals = set()
        for loc in local_locations:
            interval = (int(loc.start), int(loc.end), loc.strand)
            if interval in seen_intervals:
                out_of_order_err = f"Duplicated location interval found in join: {int(loc.start) + 1}..{int(loc.end)}"
                break
            seen_intervals.add(interval)

        if not out_of_order_err:
            for i in range(len(local_locations) - 1):
                prev_loc = local_locations[i]
                next_loc = local_locations[i+1]
                
                B_val = int(prev_loc.end)
                C_val = int(next_loc.start) + 1
                
                user_diff = C_val - B_val
                join_diffs.append(user_diff)
                
                if B_val >= C_val:
                    if strand == 1 and seq_length > 0 and B_val == seq_length and C_val == 1:
                        pass
                    else:
                        if user_diff in (0, -1):
                            out_of_order_err = "Overlapping location intervals."
                            suggest_slippage = True
                        else:
                            is_spanning_origin = (seq_length > 0 and B_val > seq_length * 0.5 and C_val < seq_length * 0.5) or (B_val - C_val > 1000)
                            if is_spanning_origin:
                                out_of_order_err = f"The location interval appears to span the origin of a circular sequence improperly. Consider shifting the starting coordinate of the sequence. (Found end {B_val} >= next start {C_val})"
                            else:
                                out_of_order_err = f"Joined segments must be in increasing order. (Found end {B_val} >= next start {C_val})"
                        break
                        
        if strand == -1:
            locations.reverse()
            
        comp_loc = CompoundLocation(locations)
        
        comp_loc._join_diffs = join_diffs
                
        if out_of_order_err:
            comp_loc._out_of_order_error = out_of_order_err
            if suggest_slippage:
                comp_loc._suggest_slippage = True
            
        if any(explicit_complements) and not all(explicit_complements):
            comp_loc._mixed_strands = True
            
        return comp_loc
        
    if "," in loc_str:
        raise LocationParseError(f"Location contains comma but lacks 'join': {loc_str}")
        
    return _parse_single_location(loc_str, seq_length=seq_length, default_strand=strand)
    

def _parse_position(pos_str):
    pos_str = pos_str.strip()
    if pos_str.startswith('<'):
        return BeforePosition(int(pos_str[1:]) - 1)
    elif pos_str.startswith('>'):
        return AfterPosition(int(pos_str[1:]) - 1)
    else:
        return ExactPosition(int(pos_str) - 1)


def _parse_single_location(loc_str, seq_length=None, default_strand=1):
    loc_str = loc_str.strip()
    ref_seq = None
    
    if ':' in loc_str:
        parts = loc_str.split(':', 1)
        ref_seq = parts[0]
        
        accession_pattern = re.compile(
            r'^([A-Z]{1}\d{5}|[A-Z]{2}\d{6}|[A-Z]{2}\d{8}|[A-Z]{4}\d{8,10}|[A-Z]{6}\d{9,11})\.\d+$', 
            re.IGNORECASE
        )
        if not accession_pattern.match(ref_seq):
            raise LocationParseError(f"Invalid remote entry reference format: '{ref_seq}'. Accession with version (e.g., AB000001.1) is required.")
            
        loc_str = parts[1]
        
    for part in loc_str.split('..'):
        part_clean = part.replace('^', '').strip()
        if '<' in part_clean[1:] or '>' in part_clean[1:]:
            raise LocationPartialDescriptorError(f"Invalid location. Partial operators '<' or '>' must only appear at the start or end. (operator placed after position numbers in '{loc_str}')")

    try:
        if '^' in loc_str:
            start_str, end_str = loc_str.split('^')
            s_val = int(start_str)
            e_val = int(end_str)
            
            is_adjacent = (e_val - s_val == 1)
            is_circular = (seq_length and s_val == seq_length and e_val == 1)
            
            if not (is_adjacent or is_circular):
                raise LocationParseError(f"Invalid caret notation '{loc_str}'. Must be n^n+1, or E^1 for circular molecules.")
                
            pos = s_val
            return FeatureLocation(ExactPosition(pos), ExactPosition(pos), strand=default_strand, ref=ref_seq)

        if '...' in loc_str:
            raise LocationParseError("Three or more consecutive dots (e.g., '1...120') are not allowed. Use '..' for ranges.")
                                                
        if '..' not in loc_str and '.' in loc_str:
            raise LocationParseError("Unknown location description with single dot (e.g., '10.12') is not supported.")

        if '..' not in loc_str:
            val = int(loc_str.replace('<', '').replace('>', ''))
            start_pos = _parse_position(loc_str)
            
            if loc_str.startswith('<'):
                end_pos = ExactPosition(val)
            elif loc_str.startswith('>'):
                end_pos = AfterPosition(val)
            else:
                end_pos = ExactPosition(val)
                
            return FeatureLocation(start_pos, end_pos, strand=default_strand, ref=ref_seq)
        
        start_str, end_str = loc_str.split('..')
        
        if start_str.startswith('>'):
            raise LocationParseError("Partial operator '>' cannot be used at the start position of a range.")
        if end_str.startswith('<'):
            raise LocationParseError("Partial operator '<' cannot be used at the end position of a range.")

        start_pos = _parse_position(start_str)
        
        end_val = int(end_str.replace('<', '').replace('>', ''))
        if end_str.startswith('>'):
            end_pos = AfterPosition(end_val)            
        elif end_str.startswith('<'):
            end_pos = BeforePosition(end_val)
        else:
            end_pos = ExactPosition(end_val)
        
        return FeatureLocation(start_pos, end_pos, strand=default_strand, ref=ref_seq)
        
    except ValueError as e:
        if "greater than or equal to start location" in str(e):
            raise LocationRangeError(f"Invalid start and end positions: {e}")
        raise LocationParseError(f"Invalid location coordinates or syntax: {e}")
    except Exception as e:
        if isinstance(e, LocationParseError):
            raise
        raise LocationParseError(f"Failed to parse location: {e}")
