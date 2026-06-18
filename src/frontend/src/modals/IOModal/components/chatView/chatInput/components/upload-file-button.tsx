import ShadTooltip from "@/components/common/shadTooltipComponent";
import {
  CHAT_UPLOAD_ATTACHMENT_ACCEPT,
  CHAT_UPLOAD_ATTACHMENT_TOOLTIP,
} from "@/constants/file-upload-constants";
import ForwardedIconComponent from "../../../../../../components/common/genericIconComponent";
import { Button } from "../../../../../../components/ui/button";

const UploadFileButton = ({
  fileInputRef,
  handleFileChange,
  handleButtonClick,
}) => {
  const handleClick = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    handleButtonClick();
  };

  return (
    <ShadTooltip
      styleClasses="z-50"
      side="right"
      content={CHAT_UPLOAD_ATTACHMENT_TOOLTIP}
    >
      <div>
        <input
          type="file"
          ref={fileInputRef}
          style={{ display: "none" }}
          onChange={handleFileChange}
          accept={CHAT_UPLOAD_ATTACHMENT_ACCEPT}
        />
        <Button
          className="h-7 w-7 px-0 flex items-center justify-center text-muted-foreground hover:text-primary"
          onClick={handleClick}
          unstyled
        >
          <ForwardedIconComponent className="h-[18px] w-[18px]" name="File" />
        </Button>
      </div>
    </ShadTooltip>
  );
};

export default UploadFileButton;
