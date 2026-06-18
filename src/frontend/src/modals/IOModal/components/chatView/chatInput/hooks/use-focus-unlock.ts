import { useEffect } from "react";

const useFocusOnUnlock = (inputRef: React.RefObject<HTMLInputElement>) => {
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, [inputRef]);

  return inputRef;
};

export default useFocusOnUnlock;
