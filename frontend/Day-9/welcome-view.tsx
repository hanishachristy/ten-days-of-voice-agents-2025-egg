// frontend/components/app/welcome-view.tsx

import { Button } from '@/components/livekit/button';

interface WelcomeViewProps {
  startButtonText: string;
  onStartCall: () => void;
}

export const WelcomeView = ({
  startButtonText, 
  onStartCall,
  ref,
}: React.ComponentProps<'div'> & WelcomeViewProps) => {
  return (
    // ----------------------------------------------------
    // 🎯 MAIN CONTAINER: Using the Renamed, Space-Free File Path
    // ----------------------------------------------------
    <div 
      ref={ref} 
      className="
        min-h-screen flex flex-col items-center justify-center 
        bg-cover bg-center bg-fixed bg-no-repeat 
        // 👇 USING THE RENAMED, RELIABLE PATH
        bg-[url('/ebay-agent-bg-murfai.jpg')] 
        relative 
      "
    >
      
      {/* Dark Overlay (Opacity 30% for testing visibility) */}
      <div className="absolute inset-0 bg-black opacity-0"></div> 

      <section className="
        relative z-10 
        bg-transparent 
        flex flex-col items-center justify-center text-center
         
        rounded-lg 
      ">
        
        {/* LOGO IMAGE */}
        <img 
            src="ebay-logo-murfai.png" 
            alt="ebay-logo-murfai" 
            className="mx-auto mb-6 w-[400px] h-auto max-w-full image-neon-gold"
        />
        
      

        {/* BUTTON */}
        <Button 
          variant="primary" 
          size="lg" 
          onClick={onStartCall} 
         className="mt-6 w-64 font-mono
                     bg-black hover:bg-black-hover
                     border-2 border-black
                     shadow-black-light
                      text-glow-burgundy-white"
        >
          START SHOPPING!
        </Button>
      </section>
    </div>
  );
};