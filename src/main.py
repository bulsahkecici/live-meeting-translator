"""Main entry point for zoom_live_translate."""
import sys
import argparse
import logging

logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Meeting Bridge: Turkish-to-English meeting audio and optional "
            "English-to-Turkish subtitles"
        )
    )
    parser.add_argument(
        '--mode',
        choices=['live', 'gui', 'dryrun', 'test', 'beep', 'list-devices'],
        default='gui',
        help='Operation mode (default: gui if available, else live)'
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config.yaml (default: config.yaml in project root)'
    )
    parser.add_argument(
        '--text',
        type=str,
        default=None,
        help='Text for dryrun mode (or read from stdin)'
    )
    
    args = parser.parse_args()
    
    # List devices mode (no config needed)
    if args.mode == 'list-devices':
        from .devices import print_device_list
        print_device_list()
        return 0

    from .config import Config
    from .pipeline import TranslationPipeline
    from .utils import setup_logging
    
    # Load configuration
    try:
        config = Config(args.config)
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}", file=sys.stderr)
        return 1
    
    # Setup logging
    setup_logging(config)
    
    # Print startup diagnostics
    logger.info("=" * 60)
    logger.info("Meeting Bridge - Starting")
    logger.info("=" * 60)
    
    # Print config summary (will be updated with effective values after pipeline init)
    logger.info(f"Config file: {config.config_path}")
    logger.info(f"DeepL API key: {'SET' if config.deepl_api_key else 'MISSING'}")
    logger.info(f"TTS engine: {config.tts_config.get('engine', 'sapi')}")
    logger.info(f"STT model: {config.stt_config.get('model', 'small')}")
    
    # Read sample rates with compat fallback
    audio_cfg = config.get('audio', {})
    input_sr = (
        config.audio_input.get('sample_rate') or
        audio_cfg.get('input_sample_rate') or
        16000
    )
    output_sr = (
        config.audio_output.get('sample_rate') or
        audio_cfg.get('output_sample_rate') or
        48000
    )
    logger.info(f"Input sample rate: {input_sr}Hz")
    logger.info(f"Output sample rate: {output_sr}Hz")
    
    # Run based on mode
    try:
        if args.mode == 'gui':
            try:
                from .ui.gui_main import run_gui
                logger.info("Starting GUI...")
                run_gui()
                return 0
            except ImportError as e:
                logger.error(f"GUI dependencies missing: {e}. Install PyQt6.", exc_info=True)
                logger.info("Falling back to live CLI mode...")
                args.mode = 'live'

        # Initialize pipeline for CLI modes
        try:
            pipeline = TranslationPipeline(config)
        except Exception as e:
            logger.error(f"Failed to initialize pipeline: {e}", exc_info=True)
            print(f"ERROR: {e}", file=sys.stderr)
            return 1

        if args.mode == 'live':
            pipeline.run_live()
        elif args.mode == 'dryrun':
            if args.text:
                text = args.text
            else:
                print("Enter Turkish text (press Enter, then Ctrl+Z and Enter to finish):")
                text = sys.stdin.read().strip()
            
            if not text:
                print("ERROR: No text provided", file=sys.stderr)
                return 1
            
            pipeline.run_dryrun(text)
        elif args.mode == 'test':
            pipeline.run_test()
        elif args.mode == 'beep':
            pipeline.run_beep()
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
