"""
Main script for running website generation on test data
Compatible with WebGen-Bench test format
"""
import sys
import os
import json
import argparse
from pathlib import Path
from typing import List, Dict, Any

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from website_generator import WebsiteGenerator
from config import DEFAULT_MODEL, ALTERNATIVE_MODEL

def load_test_data(jsonl_path: str) -> List[Dict[str, Any]]:
    """Load test data from JSONL file"""
    data = []
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                data.append(json.loads(line))
    return data

def run_single_test(instruction: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Run a single test generation"""
    print(f"\n🎯 Running single test with model: {model}")
    print(f"Instruction: {instruction[:100]}...")
    
    generator = WebsiteGenerator(model)
    result = generator.generate_website(instruction)
    
    return result

def run_test_suite(
    jsonl_path: str, 
    model: str = DEFAULT_MODEL,
    start_idx: int = 1,
    max_samples: int = None
) -> List[Dict[str, Any]]:
    """Run the full test suite"""
    print(f"\n🚀 Running test suite from: {jsonl_path}")
    print(f"Model: {model}")
    
    # Load test data
    test_data = load_test_data(jsonl_path)
    
    if max_samples:
        test_data = test_data[:max_samples]
        print(f"Limited to first {max_samples} samples")
    
    print(f"Loaded {len(test_data)} test samples")
    
    # Extract instructions
    instructions = []
    for item in test_data:
        if 'instruction' in item:
            instructions.append(item['instruction'])
        else:
            print(f"Warning: No 'instruction' field found in item: {item}")
    
    if not instructions:
        print("❌ No valid instructions found in test data")
        return []
    
    # Generate websites
    generator = WebsiteGenerator(model)
    results = generator.generate_batch(instructions, start_idx=start_idx)
    
    # Add original test data to results
    for i, result in enumerate(results):
        if i < len(test_data):
            result['original_data'] = test_data[i]
    
    return results

def create_webgen_bench_output(
    results: List[Dict[str, Any]], 
    output_dir: str,
    model_name: str
) -> None:
    """Create output in WebGen-Bench compatible format"""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\n📁 Creating WebGen-Bench compatible output in: {output_path}")
    
    # Create individual result files
    for i, result in enumerate(results):
        if result.get("success", False):
            idx = i + 1
            
            # Create JSON metadata file
            json_data = {
                "instruction": result["instruction"],
                "generated_content": result["generated_content"],
                "generation_time": result["generation_time"],
                "timestamp": result["timestamp"],
                "model": model_name,
                "api_response": result.get("api_response", {}),
                "original_data": result.get("original_data", {})
            }
            
            json_path = output_path / f"{idx:06d}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=2, ensure_ascii=False)
            
            # Create HTML file (copy from generated website)
            if "file_path" in result and Path(result["file_path"]).exists():
                html_path = output_path / f"{idx:06d}.html"
                with open(result["file_path"], 'r', encoding='utf-8') as src:
                    with open(html_path, 'w', encoding='utf-8') as dst:
                        dst.write(src.read())
            
            print(f"   Created files for sample {idx:06d}")
    
    # Create summary
    successful = len([r for r in results if r.get("success", False)])
    summary = {
        "model": model_name,
        "total_samples": len(results),
        "successful": successful,
        "failed": len(results) - successful,
        "success_rate": successful / len(results) if results else 0,
        "timestamp": results[0]["timestamp"] if results else None
    }
    
    summary_path = output_path / "summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    print(f"✅ WebGen-Bench output created successfully")
    print(f"   Success rate: {summary['success_rate']:.2%}")

def main():
    """Main function with command line interface"""
    parser = argparse.ArgumentParser(description="Alternative Website Generation for WebGen-Bench")
    
    parser.add_argument("--instruction", type=str, help="Single instruction for website generation")
    parser.add_argument("--jsonl_path", type=str, help="Path to JSONL test data file")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, 
                       choices=[DEFAULT_MODEL, ALTERNATIVE_MODEL],
                       help=f"Model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--output_dir", type=str, default="alternative_results",
                       help="Output directory for results (default: alternative_results)")
    parser.add_argument("--max_samples", type=int, help="Maximum number of samples to process")
    parser.add_argument("--start_idx", type=int, default=1, help="Starting index for file naming")
    
    args = parser.parse_args()
    
    if not args.instruction and not args.jsonl_path:
        print("❌ Please provide either --instruction for single test or --jsonl_path for batch test")
        return False
    
    if args.instruction:
        # Single test mode
        result = run_single_test(args.instruction, args.model)
        
        if result["success"]:
            print(f"✅ Single test completed successfully")
            print(f"   Generated file: {result['filename']}")
            return True
        else:
            print(f"❌ Single test failed: {result.get('error', {}).get('message', 'Unknown error')}")
            return False
    
    else:
        # Batch test mode
        if not os.path.exists(args.jsonl_path):
            print(f"❌ Test data file not found: {args.jsonl_path}")
            return False
        
        results = run_test_suite(
            args.jsonl_path, 
            args.model, 
            args.start_idx,
            args.max_samples
        )
        
        if not results:
            print("❌ No results generated")
            return False
        
        # Create WebGen-Bench compatible output
        create_webgen_bench_output(results, args.output_dir, args.model)
        
        successful = len([r for r in results if r.get("success", False)])
        print(f"\n🎉 Batch processing completed: {successful}/{len(results)} successful")
        
        return successful > 0

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
