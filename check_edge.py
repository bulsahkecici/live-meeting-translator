
import sys
import inspect
try:
    import edge_tts
    print(f"edge_tts version: {edge_tts.__version__}")
    print(f"edge_tts file: {edge_tts.__file__}")
    
    sig = inspect.signature(edge_tts.Communicate)
    print(f"Communicate signature: {sig}")
    
    if "output_format" in sig.parameters:
        print("output_format IS supported")
    else:
        print("output_format IS NOT supported")
        
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"Error: {e}")
